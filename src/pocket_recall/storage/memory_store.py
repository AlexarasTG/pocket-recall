"""Save memories, keep older versions for recovery, and update the search index."""

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pocket_recall.config import MemoryConfig
from pocket_recall.embeddings.model_lifecycle_manager import ModelLifecycleManager
from pocket_recall.errors import EmbeddingError, MemoryLookupError
from pocket_recall.models import (
    ArchivedMemoryEntry,
    MemoryPreSaveDraft,
    MemoryRecord,
    SearchResults,
)
from pocket_recall.retrieval.index_synchronizer import IndexSynchronizer
from pocket_recall.retrieval.search_coordinator import SearchCoordinator
from pocket_recall.storage.archived_memory_store import (
    ArchivedMemoryStore,
    record_from_row,
)
from pocket_recall.storage.database import MemoryDatabase
from pocket_recall.storage.search_store import SearchStore
from pocket_recall.validation import validate_draft

logger = logging.getLogger(__name__)


class ConcurrentUpdateError(RuntimeError):
    """The memory changed after it was shown for approval."""


class MemoryStore:
    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self.database = MemoryDatabase(config.memory_database)
        self.archive_store = ArchivedMemoryStore()
        self.model_lifecycle_manager = ModelLifecycleManager(config)
        self.search_store = SearchStore(
            config.search_database, self.model_lifecycle_manager.specification, self.model_lifecycle_manager.dimensions
        )
        self.index_synchronizer = IndexSynchronizer(self.database, self.search_store, self.model_lifecycle_manager)
        self.search_coordinator = SearchCoordinator(
            config, self.database, self.search_store, self.model_lifecycle_manager
        )

    def initialize(self) -> None:
        self.database.initialize()
        self.model_lifecycle_manager.prepare()
        self.index_synchronizer.initialize()

    def create(self, draft: MemoryPreSaveDraft) -> MemoryRecord:
        validate_draft(draft)
        with self.database.write() as connection:
            now = datetime.now(timezone.utc)
            record = MemoryRecord(
                id=str(uuid4()),
                title=draft.title,
                body=draft.body,
                aliases=draft.aliases,
                created_at=now,
                updated_at=now,
            )
            self._save(connection, record)
            self._purge_expired(connection, now)
        self._synchronize_index(record.id)
        return record

    def update(
        self,
        memory_id: str,
        draft: MemoryPreSaveDraft,
        *,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        validate_draft(draft)
        with self.database.write() as connection:
            current = self._get_record(connection, memory_id)
            if current.deleted_at is not None:
                raise MemoryLookupError("Memory is deleted; restore it before editing")
            self._check_version(current, expected_updated_at)
            record = replace(
                current,
                title=draft.title,
                body=draft.body,
                aliases=draft.aliases,
                updated_at=self._next_timestamp(current),
            )
            self._replace(connection, current, record)
        self._synchronize_index(record.id)
        return record

    def delete(
        self,
        memory_id: str,
        *,
        expected_updated_at: datetime | None = None,
    ) -> None:
        with self.database.write() as connection:
            current = self._get_record(connection, memory_id)
            if current.deleted_at is not None:
                raise MemoryLookupError("Memory is already deleted")
            self._check_version(current, expected_updated_at)
            now = self._next_timestamp(current)
            self._replace(connection, current, replace(current, updated_at=now, deleted_at=now))
        self._synchronize_index(memory_id)

    def restore(
        self,
        memory_id: str,
        *,
        revision_id: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        with self.database.write() as connection:
            current = self._get_record(connection, memory_id)
            self._check_version(current, expected_updated_at)
            now = self._next_timestamp(current)
            if revision_id is not None:
                content = self.archive_store.fetch(connection, memory_id, revision_id, now).record
            elif current.deleted_at is not None:
                content = current
            else:
                raise ValueError("Select a revision to restore an active memory")
            validate_draft(
                MemoryPreSaveDraft(
                    title=content.title,
                    body=content.body,
                    aliases=content.aliases,
                )
            )
            record = replace(
                current,
                title=content.title,
                body=content.body,
                aliases=content.aliases,
                updated_at=now,
                deleted_at=None,
            )
            self._replace(connection, current, record)
        self._synchronize_index(record.id)
        return record

    def search(self, query: str) -> SearchResults:
        return self.search_coordinator.search(query)

    def reindex(self) -> None:
        self.index_synchronizer.rebuild()

    def index_update_pending(self) -> bool:
        with self.search_store.snapshot(self.database) as connection:
            return self.search_store.has_pending_updates(connection)

    def _synchronize_index(self, memory_id: str) -> None:
        try:
            self.index_synchronizer.synchronize(memory_id=memory_id)
        except (OSError, sqlite3.Error, ValueError, EmbeddingError) as error:
            # Canonical content is already committed. Keep its pending request
            # rather than report that the approved save failed.
            logger.warning("Search index update pending: %s", error)

    def fetch(self, memory_id: str) -> MemoryRecord:
        with self.database.read() as connection:
            record = self._get_record(connection, memory_id)
            if record.deleted_at is not None:
                raise MemoryLookupError("Memory is deleted; use the recovery commands")
            return record

    def fetch_deleted(self, memory_id: str) -> MemoryRecord:
        with self.database.read() as connection:
            record = self._get_record(connection, memory_id)
            if record.deleted_at is None:
                raise MemoryLookupError("Memory is not deleted")
            return record

    def list_records(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        self._check_page(limit, offset)
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE deleted_at IS NULL ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return tuple(record_from_row(row) for row in rows)

    def list_deleted(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        self._check_page(limit, offset)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.recovery_retention_days)
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE deleted_at > ? ORDER BY id LIMIT ? OFFSET ?",
                (cutoff.isoformat(), limit, offset),
            ).fetchall()
            return tuple(record_from_row(row) for row in rows)

    def history(
        self,
        memory_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ArchivedMemoryEntry, ...]:
        self._check_page(limit, offset)
        with self.database.read() as connection:
            self._get_record(connection, memory_id)
            return self.archive_store.list_for_memory(
                connection,
                memory_id,
                datetime.now(timezone.utc),
                limit=limit,
                offset=offset,
            )

    def fetch_revision(self, memory_id: str, revision_id: str) -> ArchivedMemoryEntry:
        with self.database.read() as connection:
            self._get_record(connection, memory_id)
            return self.archive_store.fetch(connection, memory_id, revision_id, datetime.now(timezone.utc))

    def _get_record(self, connection: sqlite3.Connection, memory_id: str) -> MemoryRecord:
        row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise MemoryLookupError("Memory not found")
        record = record_from_row(row)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.recovery_retention_days)
        if record.deleted_at is not None and record.deleted_at <= cutoff:
            raise MemoryLookupError("The memory's recovery window has expired")
        return record

    def _replace(
        self,
        connection: sqlite3.Connection,
        current: MemoryRecord,
        record: MemoryRecord,
    ) -> None:
        self.archive_store.retain(connection, current, record.updated_at, self.config.recovery_retention_days)
        self._save(connection, record)
        self._purge_expired(connection, record.updated_at)

    def _save(self, connection: sqlite3.Connection, record: MemoryRecord) -> None:
        connection.execute(
            """INSERT INTO memories (id, title, body, aliases, created_at, updated_at, deleted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET title = excluded.title, body = excluded.body,
                   aliases = excluded.aliases, updated_at = excluded.updated_at,
                   deleted_at = excluded.deleted_at""",
            (
                record.id,
                record.title,
                record.body,
                json.dumps(record.aliases),
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.deleted_at.isoformat() if record.deleted_at else None,
            ),
        )
        connection.execute(
            """INSERT INTO pending_index_updates (memory_id, requested_at) VALUES (?, ?)
               ON CONFLICT(memory_id) DO UPDATE SET requested_at = excluded.requested_at""",
            (record.id, record.updated_at.isoformat()),
        )

    def _purge_expired(self, connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute("DELETE FROM revisions WHERE expires_at <= ?", (now.isoformat(),))
        cutoff = now - timedelta(days=self.config.recovery_retention_days)
        connection.execute("DELETE FROM memories WHERE deleted_at <= ?", (cutoff.isoformat(),))

    @staticmethod
    def _check_version(record: MemoryRecord, expected: datetime | None) -> None:
        if expected is not None and record.updated_at != expected:
            raise ConcurrentUpdateError("Memory changed after preview; read it again before saving")

    @staticmethod
    def _next_timestamp(record: MemoryRecord) -> datetime:
        return max(datetime.now(timezone.utc), record.updated_at + timedelta(microseconds=1))

    @staticmethod
    def _check_page(limit: int, offset: int) -> None:
        if limit <= 0 or offset < 0:
            raise ValueError("Limit must be positive and offset must not be negative")
