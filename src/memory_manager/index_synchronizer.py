"""Update the search index from saved memories. Keep failed updates for retry."""

from memory_manager.database import MemoryDatabase
from memory_manager.archived_memory_store import record_from_row
from memory_manager.search_store import SearchStore


class IndexSynchronizer:
    def __init__(self, database: MemoryDatabase, index: SearchStore) -> None:
        self.database = database
        self.index = index

    def initialize(self) -> None:
        self.index.initialize()
        with self.index.read() as connection:
            ready = connection.execute("SELECT ready FROM index_state WHERE id = 1").fetchone()[0]
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
                if not indexed.execute("SELECT ready FROM index_state WHERE id = 1").fetchone()[0]:
                    raise ValueError("Search index is not ready; run memory reindex")
                for entry in pending:
                    row = canonical.execute(
                        "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL", (entry[0],)
                    ).fetchone()
                    if row is None:
                        self.index.remove(indexed, entry[0])
                    else:
                        self.index.replace(indexed, record_from_row(row))
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
                    self.index.replace(indexed, record_from_row(row))
                indexed.execute("UPDATE index_state SET ready = 1 WHERE id = 1")
            canonical.execute("DELETE FROM pending_index_updates")
