"""Send Pocket Recall operations to its shared background service."""

import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pocket_recall.config import MemoryConfig
from pocket_recall.errors import ConcurrentUpdateError, MemoryLookupError, ServiceError
from pocket_recall.models import (
    ArchivedMemoryEntry,
    MemoryPreSaveDraft,
    MemoryRecord,
    SearchCandidate,
    SearchResults,
)
from pocket_recall.transport.service_protocol import (
    PROTOCOL_VERSION,
    decode_message,
    encode_message,
    request_message,
)


class PocketRecallClient:
    """Provide Pocket Recall operations to command-line tools and apps.

    Each operation uses one short-lived Unix-socket connection. The client
    starts the background service automatically when it is not running.
    """

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self.config = config or MemoryConfig()

    def create(self, draft: MemoryPreSaveDraft) -> MemoryRecord:
        return self._record(self._request("memory.create", self._draft_arguments(draft)))

    def update(
        self,
        memory_id: str,
        draft: MemoryPreSaveDraft,
        *,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        return self._record(
            self._request(
                "memory.update",
                {
                    "memory_id": memory_id,
                    **self._draft_arguments(draft),
                    "expected_updated_at": self._date_text(expected_updated_at),
                },
            )
        )

    def delete(self, memory_id: str, *, expected_updated_at: datetime | None = None) -> None:
        self._request(
            "memory.delete",
            {"memory_id": memory_id, "expected_updated_at": self._date_text(expected_updated_at)},
        )

    def restore(
        self,
        memory_id: str,
        *,
        revision_id: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        return self._record(
            self._request(
                "memory.restore",
                {
                    "memory_id": memory_id,
                    "revision_id": revision_id,
                    "expected_updated_at": self._date_text(expected_updated_at),
                },
            )
        )

    def fetch(self, memory_id: str) -> MemoryRecord:
        return self._record(self._request("memory.get", {"memory_id": memory_id}))

    def list_records(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        result = self._list_result(self._request("memory.list", {"limit": limit, "offset": offset}))
        return tuple(self._record(item) for item in result)

    def fetch_deleted(self, memory_id: str) -> MemoryRecord:
        return self._record(self._request("deleted.get", {"memory_id": memory_id}))

    def list_deleted(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        result = self._list_result(self._request("deleted.list", {"limit": limit, "offset": offset}))
        return tuple(self._record(item) for item in result)

    def fetch_revision(self, memory_id: str, revision_id: str) -> ArchivedMemoryEntry:
        result = self._object_result(self._request("archive.get", {"memory_id": memory_id, "revision_id": revision_id}))
        return self._archived_entry(result)

    def history(self, memory_id: str, *, limit: int = 50, offset: int = 0) -> tuple[ArchivedMemoryEntry, ...]:
        result = self._list_result(
            self._request("archive.list", {"memory_id": memory_id, "limit": limit, "offset": offset})
        )
        return tuple(self._archived_entry(item) for item in result)

    def search(self, query: str) -> SearchResults:
        result = self._object_result(
            self._request(
                "search",
                {
                    "query": query,
                    "semantic_policy": self.config.semantic_fallback_policy,
                    "similarity_threshold": self.config.semantic_similarity_threshold,
                },
            )
        )
        candidates = self._list_result(result.get("candidates"))
        return SearchResults(
            candidates=tuple(self._candidate(item) for item in candidates),
            index_update_pending=self._boolean(result, "index_update_pending"),
        )

    def initialize(self) -> Path:
        result = self._object_result(self._request("maintenance.init", {}))
        path = result.get("memory_database")
        if not isinstance(path, str):
            raise ServiceError("internal_error", "Service returned an invalid database path")
        return Path(path)

    def reindex(self) -> None:
        self._request("maintenance.reindex", {})

    def index_update_pending(self) -> bool:
        result = self._object_result(self._request("maintenance.status", {}))
        return self._boolean(result, "index_update_pending")

    def health(self) -> bool:
        result = self._object_result(self._request("service.health", {}))
        return result.get("status") == "ready"

    def stop(self) -> bool:
        try:
            self._request("service.stop", {}, start_service=False)
        except (ConnectionError, FileNotFoundError, OSError):
            return False
        return True

    def _request(self, operation: str, arguments: dict[str, object], *, start_service: bool = True) -> object:
        request_id = str(uuid4())
        data = encode_message(request_message(request_id, operation, arguments))
        if len(data) > self.config.max_socket_request_bytes:
            raise ValueError("Request is too large")
        timeout = (
            self.config.maintenance_request_timeout_seconds
            if operation in ("maintenance.init", "maintenance.reindex")
            else self.config.normal_request_timeout_seconds
        )
        try:
            response = self._exchange(data, timeout)
        except (FileNotFoundError, ConnectionRefusedError):
            if not start_service:
                raise
            self._start_service()
            response = self._exchange(data, timeout)
        return self._result(response, request_id)

    def _exchange(self, data: bytes, timeout: int) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(self.config.service_socket))
            connection.sendall(data)
            with connection.makefile("rb") as response:
                line = response.readline()
        if not line:
            raise ConnectionError("Pocket Recall service closed the connection without a response")
        return decode_message(line)

    def _start_service(self) -> None:
        self.config.data_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        subprocess.Popen(
            [sys.executable, "-m", "pocket_recall.daemon"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        deadline = time.monotonic() + self.config.socket_startup_timeout_seconds
        while time.monotonic() < deadline:
            try:
                health_id = str(uuid4())
                response = self._exchange(
                    encode_message(request_message(health_id, "service.health", {})),
                    self.config.socket_startup_timeout_seconds,
                )
                if self._result(response, health_id) == {"status": "ready"}:
                    return
            except (FileNotFoundError, ConnectionRefusedError, ConnectionError):
                time.sleep(0.05)
        raise ServiceError(
            "unavailable",
            f"Pocket Recall service did not start within {self.config.socket_startup_timeout_seconds} seconds",
        )

    @staticmethod
    def _result(response: dict[str, Any], request_id: str) -> object:
        if response.get("protocol_version") != PROTOCOL_VERSION or response.get("request_id") != request_id:
            raise ServiceError("internal_error", "Service returned an invalid response envelope")
        if response.get("success") is True and "result" in response:
            return response["result"]
        error = response.get("error")
        if response.get("success") is not False or not isinstance(error, dict):
            raise ServiceError("internal_error", "Service returned an invalid response envelope")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            raise ServiceError("internal_error", "Service returned an invalid error")
        if code == "not_found":
            raise MemoryLookupError(message)
        if code == "conflict":
            raise ConcurrentUpdateError(message)
        raise ServiceError(code, message)

    @staticmethod
    def _draft_arguments(draft: MemoryPreSaveDraft) -> dict[str, object]:
        return {"title": draft.title, "body": draft.body, "aliases": list(draft.aliases)}

    @staticmethod
    def _date_text(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _object_result(result: object) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ServiceError("internal_error", "Service returned an invalid result")
        return result

    @staticmethod
    def _list_result(result: object) -> list[dict[str, Any]]:
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise ServiceError("internal_error", "Service returned an invalid list")
        return result

    @staticmethod
    def _boolean(result: dict[str, Any], name: str) -> bool:
        value = result.get(name)
        if not isinstance(value, bool):
            raise ServiceError("internal_error", f"Service returned an invalid {name}")
        return value

    @staticmethod
    def _record(result: object) -> MemoryRecord:
        value = PocketRecallClient._object_result(result)
        aliases = value.get("aliases")
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ServiceError("internal_error", "Service returned invalid memory aliases")
        try:
            return MemoryRecord(
                id=str(value["id"]),
                title=str(value["title"]),
                body=str(value["body"]),
                aliases=tuple(aliases),
                created_at=datetime.fromisoformat(str(value["created_at"])),
                updated_at=datetime.fromisoformat(str(value["updated_at"])),
                deleted_at=(
                    datetime.fromisoformat(str(value["deleted_at"])) if value.get("deleted_at") is not None else None
                ),
            )
        except (KeyError, ValueError) as error:
            raise ServiceError("internal_error", "Service returned an invalid memory") from error

    @staticmethod
    def _archived_entry(value: dict[str, Any]) -> ArchivedMemoryEntry:
        try:
            return ArchivedMemoryEntry(
                id=str(value["id"]),
                record=PocketRecallClient._record(value["record"]),
                retained_at=datetime.fromisoformat(str(value["retained_at"])),
                expires_at=datetime.fromisoformat(str(value["expires_at"])),
            )
        except (KeyError, ValueError) as error:
            raise ServiceError("internal_error", "Service returned an invalid archived memory") from error

    @staticmethod
    def _candidate(value: dict[str, Any]) -> SearchCandidate:
        try:
            return SearchCandidate(
                id=str(value["id"]),
                title=str(value["title"]),
                aliases=tuple(str(alias) for alias in value["aliases"]),
                updated_at=datetime.fromisoformat(str(value["updated_at"])),
                match_kind=value["match_kind"],
                score=float(value["score"]),
                excerpt=str(value.get("excerpt", "")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ServiceError("internal_error", "Service returned an invalid search candidate") from error
