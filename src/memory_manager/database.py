"""SQLite connections and the tables owned by this application."""

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


class MemoryDatabase:
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
            if version == SCHEMA_VERSION and application == APPLICATION_ID:
                return
            has_tables = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone()
            if version or application or has_tables:
                raise ValueError("This file is not an empty or supported memory database")
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
            raise ValueError("Memory database is not initialized; run memory init")
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            if version != SCHEMA_VERSION or application != APPLICATION_ID:
                raise ValueError("Unsupported memory database; no changes were made")
            yield connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self.read() as connection:
            # Take the write lock before reading the version we intend to replace.
            connection.execute("BEGIN IMMEDIATE")
            yield connection
