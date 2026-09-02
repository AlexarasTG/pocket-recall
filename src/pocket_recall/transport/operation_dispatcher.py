"""Connect service operation names to the code that performs them."""

import logging
import sqlite3
from datetime import datetime
from typing import Any, Callable

from pocket_recall.models import MemoryPreSaveDraft
from pocket_recall.storage.database_snapshot_manager import DatabaseSnapshotManager
from pocket_recall.storage.memory_store import MemoryStore
from pocket_recall.storage.retrieval_audit_store import RetrievalAuditStore

logger = logging.getLogger(__name__)


class OperationDispatcher:
    """Check request arguments and call the matching store method."""

    def __init__(
        self,
        store: MemoryStore,
        audit_store: RetrievalAuditStore,
        snapshot_manager: DatabaseSnapshotManager,
        *,
        index_changed: Callable[[], None],
        stop_service: Callable[[], None],
    ) -> None:
        self.store = store
        self.audit_store = audit_store
        self.snapshot_manager = snapshot_manager
        self.index_changed = index_changed
        self.stop_service = stop_service

    def dispatch(self, operation: str, arguments: dict[str, Any]) -> tuple[object, tuple[str, ...]]:
        handlers: dict[str, Callable[[dict[str, Any]], object]] = {
            "memory.create": self._create,
            "memory.update": self._update,
            "memory.delete": self._delete,
            "memory.restore": self._restore,
            "memory.get": self._get,
            "memory.list": self._list,
            "deleted.get": self._get_deleted,
            "deleted.list": self._list_deleted,
            "archive.get": self._get_archive,
            "archive.list": self._list_archive,
            "search": self._search,
            "maintenance.init": self._initialize,
            "maintenance.status": self._status,
            "maintenance.reindex": self._reindex,
            "service.health": self._health,
            "service.stop": self._stop,
        }
        try:
            handler = handlers[operation]
        except KeyError as error:
            raise ValueError(f"Unknown operation: {operation}") from error
        warnings = self._create_snapshot_before(operation)
        return handler(arguments), warnings

    def _create_snapshot_before(self, operation: str) -> tuple[str, ...]:
        if operation not in ("memory.create", "memory.update", "memory.delete", "memory.restore"):
            return ()
        try:
            self.snapshot_manager.create_daily_snapshot()
        except (OSError, sqlite3.Error, ValueError) as error:
            message = f"Daily database snapshot failed: {error}"
            logger.warning(message)
            return (message,)
        return ()

    def _create(self, arguments: dict[str, Any]) -> object:
        result = self.store.create(self._draft(arguments))
        self.index_changed()
        return result

    def _update(self, arguments: dict[str, Any]) -> object:
        result = self.store.update(
            self._text(arguments, "memory_id"),
            self._draft(arguments),
            expected_updated_at=self._optional_datetime(arguments, "expected_updated_at"),
        )
        self.index_changed()
        return result

    def _delete(self, arguments: dict[str, Any]) -> object:
        self.store.delete(
            self._text(arguments, "memory_id"),
            expected_updated_at=self._optional_datetime(arguments, "expected_updated_at"),
        )
        self.index_changed()
        return None

    def _restore(self, arguments: dict[str, Any]) -> object:
        result = self.store.restore(
            self._text(arguments, "memory_id"),
            revision_id=self._optional_text(arguments, "revision_id"),
            expected_updated_at=self._optional_datetime(arguments, "expected_updated_at"),
        )
        self.index_changed()
        return result

    def _get(self, arguments: dict[str, Any]) -> object:
        return self.store.fetch(self._text(arguments, "memory_id"))

    def _list(self, arguments: dict[str, Any]) -> object:
        return self.store.list_records(
            limit=self._page(arguments, "limit", 50), offset=self._page(arguments, "offset", 0)
        )

    def _get_deleted(self, arguments: dict[str, Any]) -> object:
        return self.store.fetch_deleted(self._text(arguments, "memory_id"))

    def _list_deleted(self, arguments: dict[str, Any]) -> object:
        return self.store.list_deleted(
            limit=self._page(arguments, "limit", 50), offset=self._page(arguments, "offset", 0)
        )

    def _get_archive(self, arguments: dict[str, Any]) -> object:
        return self.store.fetch_revision(self._text(arguments, "memory_id"), self._text(arguments, "revision_id"))

    def _list_archive(self, arguments: dict[str, Any]) -> object:
        return self.store.history(
            self._text(arguments, "memory_id"),
            limit=self._page(arguments, "limit", 50),
            offset=self._page(arguments, "offset", 0),
        )

    def _search(self, arguments: dict[str, Any]) -> object:
        policy = self._optional_text(arguments, "semantic_policy")
        if policy not in (None, "on_zero_results", "fill_remaining_slots"):
            raise ValueError("semantic_policy must be on_zero_results or fill_remaining_slots")
        threshold = arguments.get("similarity_threshold")
        if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float))):
            raise ValueError("similarity_threshold must be a number")
        return self.store.search(
            self._text(arguments, "query"),
            semantic_policy=policy,
            similarity_threshold=float(threshold) if threshold is not None else None,
        )

    def _initialize(self, arguments: dict[str, Any]) -> object:
        self._empty(arguments)
        self.store.initialize()
        self.audit_store.initialize()
        return {"memory_database": str(self.store.config.memory_database), "index_update_pending": False}

    def _status(self, arguments: dict[str, Any]) -> object:
        self._empty(arguments)
        return {
            "index_update_pending": self.store.index_update_pending(),
            "retrieval_audit": self.audit_store.status(),
        }

    def _reindex(self, arguments: dict[str, Any]) -> object:
        self._empty(arguments)
        self.store.reindex()
        return {"index_update_pending": False}

    def _health(self, arguments: dict[str, Any]) -> object:
        self._empty(arguments)
        return {"status": "ready"}

    def _stop(self, arguments: dict[str, Any]) -> object:
        self._empty(arguments)
        self.stop_service()
        return {"status": "stopping"}

    @staticmethod
    def _draft(arguments: dict[str, Any]) -> MemoryPreSaveDraft:
        title = OperationDispatcher._text(arguments, "title")
        body = OperationDispatcher._text(arguments, "body")
        aliases = arguments.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError("aliases must be a list of strings")
        return MemoryPreSaveDraft(title=title, body=body, aliases=tuple(aliases))

    @staticmethod
    def _text(arguments: dict[str, Any], name: str) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
        return value

    @staticmethod
    def _optional_text(arguments: dict[str, Any], name: str) -> str | None:
        value = arguments.get(name)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"{name} must be a non-empty string when supplied")
        return value

    @staticmethod
    def _optional_datetime(arguments: dict[str, Any], name: str) -> datetime | None:
        value = OperationDispatcher._optional_text(arguments, name)
        if value is None:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{name} must be an ISO-8601 date and time") from error

    @staticmethod
    def _page(arguments: dict[str, Any], name: str, default: int) -> int:
        value = arguments.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        return value

    @staticmethod
    def _empty(arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("This operation takes no arguments")
