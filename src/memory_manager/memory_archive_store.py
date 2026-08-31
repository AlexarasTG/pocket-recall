"""Keep older content in the same transaction as the edit that replaces it."""

from datetime import datetime, timedelta
import json
import sqlite3
from uuid import uuid4

from memory_manager.models import MemoryRecord, ArchivedMemoryEntry


def record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["memory_id"] if "memory_id" in row.keys() else row["id"],
        title=row["title"],
        body=row["body"],
        aliases=tuple(json.loads(row["aliases"])),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
    )


def archived_entry_from_row(row: sqlite3.Row) -> ArchivedMemoryEntry:
    return ArchivedMemoryEntry(
        id=row["id"],
        record=record_from_row(row),
        retained_at=datetime.fromisoformat(row["retained_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
    )


class MemoryArchiveStore:
    def retain(
        self,
        connection: sqlite3.Connection,
        record: MemoryRecord,
        now: datetime,
        retention_days: int,
    ) -> None:
        connection.execute(
            """INSERT INTO revisions
               (id, memory_id, title, body, aliases, created_at, updated_at,
                deleted_at, retained_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), record.id, record.title, record.body,
                json.dumps(record.aliases), record.created_at.isoformat(),
                record.updated_at.isoformat(),
                record.deleted_at.isoformat() if record.deleted_at else None,
                now.isoformat(), (now + timedelta(days=retention_days)).isoformat(),
            ),
        )

    def list_for_memory(
        self, connection: sqlite3.Connection, memory_id: str, now: datetime,
        *, limit: int, offset: int,
    ) -> tuple[ArchivedMemoryEntry, ...]:
        rows = connection.execute(
            """SELECT * FROM revisions WHERE memory_id = ? AND expires_at > ?
               ORDER BY retained_at DESC, id LIMIT ? OFFSET ?""",
            (memory_id, now.isoformat(), limit, offset),
        ).fetchall()
        return tuple(archived_entry_from_row(row) for row in rows)

    def fetch(
        self, connection: sqlite3.Connection, memory_id: str,
        revision_id: str, now: datetime,
    ) -> ArchivedMemoryEntry:
        row = connection.execute(
            """SELECT * FROM revisions
               WHERE id = ? AND memory_id = ? AND expires_at > ?""",
            (revision_id, memory_id, now.isoformat()),
        ).fetchone()
        if row is None:
            raise LookupError("Revision not found or its recovery window has expired")
        return archived_entry_from_row(row)
