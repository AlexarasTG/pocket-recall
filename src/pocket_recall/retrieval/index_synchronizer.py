"""Update the search index from saved memories. Keep failed updates for retry."""

from pocket_recall.embeddings.model_lifecycle_manager import ModelLifecycleManager
from pocket_recall.storage.archived_memory_store import record_from_row
from pocket_recall.storage.database import MemoryDatabase
from pocket_recall.storage.search_store import SearchStore


class IndexSynchronizer:
    def __init__(
        self, database: MemoryDatabase, index: SearchStore, model_lifecycle_manager: ModelLifecycleManager
    ) -> None:
        self.database = database
        self.index = index
        self.model_lifecycle_manager = model_lifecycle_manager

    def initialize(self) -> None:
        self.index.initialize()
        with self.index.read() as connection:
            ready = self.index.is_ready(connection)
        if not ready:
            self.rebuild()

    def synchronize(self, *, memory_id: str | None = None, limit: int = 100) -> int:
        """Apply up to `limit` pending updates. The caller decides when to retry failures."""
        if limit <= 0:
            raise ValueError("Synchronization limit must be positive")
        with self.database.write() as canonical:
            pending = canonical.execute(
                """SELECT memory_id FROM pending_index_updates
                   WHERE (? IS NULL OR memory_id = ?) ORDER BY requested_at, memory_id LIMIT ?""",
                (memory_id, memory_id, limit),
            ).fetchall()
            with self.index.write() as indexed:
                if not self.index.is_ready(indexed):
                    raise ValueError("Search index is not ready for this model; run memory maintenance reindex")
                for entry in pending:
                    row = canonical.execute(
                        "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL", (entry[0],)
                    ).fetchone()
                    if row is None:
                        self.index.remove(indexed, entry[0])
                    else:
                        record = record_from_row(row)
                        self.index.replace(indexed, record, self.model_lifecycle_manager.embed_record(record))
            # A crash before this commit leaves requests safe to replay. Holding the
            # canonical write lock prevents acknowledging a newer, unindexed edit.
            canonical.executemany(
                "DELETE FROM pending_index_updates WHERE memory_id = ?",
                [(entry[0],) for entry in pending],
            )
        return len(pending)

    def rebuild(self) -> None:
        """Rebuild the search index without changing saved memories or their dates."""
        with self.database.write() as canonical:
            self.index.initialize()
            with self.index.write() as indexed:
                self.index.clear(indexed)
                for row in canonical.execute("SELECT * FROM memories WHERE deleted_at IS NULL ORDER BY id"):
                    record = record_from_row(row)
                    self.index.replace(indexed, record, self.model_lifecycle_manager.embed_record(record))
                self.index.mark_ready(indexed)
            canonical.execute("DELETE FROM pending_index_updates")
