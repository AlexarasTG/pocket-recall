"""Create database tables and manage SQLite connections."""

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
from typing import Iterator


SCHEMA_VERSION = 1
APPLICATION_ID = 0x4D454D31

SCHEMA = (
    """CREATE TABLE memories (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        aliases TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    )""",
    """CREATE TABLE revisions (
        id TEXT PRIMARY KEY,
        memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        aliases TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        retained_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    "CREATE INDEX revisions_by_memory ON revisions(memory_id, retained_at, id)",
    "CREATE INDEX revisions_by_expiry ON revisions(expires_at)",
    "CREATE INDEX memories_by_deletion ON memories(deleted_at)",
    # Deletion requests must survive removal of expired canonical records.
    """CREATE TABLE pending_index_updates (
        memory_id TEXT PRIMARY KEY,
        requested_at TEXT NOT NULL
    )""",
)


class SQLiteDatabase:
    schema: tuple[str, ...]
    application_id: int
    schema_version = SCHEMA_VERSION

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            if version == self.schema_version and application == self.application_id:
                return
            has_tables = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone()
            if version or application or has_tables:
                raise ValueError(f"Not an empty or supported database: {self.path}")
            for statement in self.schema:
                connection.execute(statement)
            connection.execute(f"PRAGMA application_id = {self.application_id}")
            connection.execute(f"PRAGMA user_version = {self.schema_version}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise ValueError(f"Database is not initialized; run memory maintenance init: {self.path}")
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            if version != self.schema_version or application != self.application_id:
                raise ValueError(f"Unsupported database; no changes were made: {self.path}")
            yield connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self.read() as connection:
            # Take the write lock before reading the version we intend to replace.
            connection.execute("BEGIN IMMEDIATE")
            yield connection


class MemoryDatabase(SQLiteDatabase):
    schema = SCHEMA
    application_id = APPLICATION_ID
