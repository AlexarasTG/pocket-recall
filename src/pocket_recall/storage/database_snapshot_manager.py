"""Create and restore daily copies of the canonical database."""

import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from threading import Lock

from pocket_recall.config import MemoryConfig
from pocket_recall.storage.database import MemoryDatabase


class DatabaseSnapshotManager:
    """Keep valid daily database snapshots and restore a selected date."""

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self._creation_lock = Lock()

    def create_daily_snapshot(self) -> None:
        with self._creation_lock:
            snapshot = self._snapshot_path(datetime.now().astimezone().date())
            if snapshot.is_file() or not self.config.memory_database.is_file():
                return
            self._validate_database(self.config.memory_database)
            self.config.snapshot_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self._temporary_file(self.config.snapshot_directory, snapshot.name)
            try:
                with self._connect_read_only(self.config.memory_database) as source:
                    with sqlite3.connect(temporary) as destination:
                        source.backup(destination)
                os.chmod(temporary, 0o600)
                self._validate_database(temporary)
                os.replace(temporary, snapshot)
                self._remove_old_snapshots()
            finally:
                temporary.unlink(missing_ok=True)

    def restore_snapshot(self, snapshot_date: str) -> None:
        selected = self._snapshot_path(self._parse_date(snapshot_date))
        if not selected.is_file():
            raise ValueError(f"No database snapshot exists for {snapshot_date}")
        self._validate_database(selected)

        temporary = self._temporary_file(self.config.data_directory, "memory-restore")
        safety_copy = self._temporary_file(self.config.data_directory, "memory-before-restore")
        try:
            shutil.copyfile(selected, temporary)
            os.chmod(temporary, 0o600)
            self._validate_database(temporary)
            if self.config.memory_database.is_file():
                shutil.copyfile(self.config.memory_database, safety_copy)
                os.chmod(safety_copy, 0o600)
                os.replace(safety_copy, self.config.database_before_restore)
            os.replace(temporary, self.config.memory_database)
            self._remove_database_sidecars()
        finally:
            temporary.unlink(missing_ok=True)
            safety_copy.unlink(missing_ok=True)

    def _remove_old_snapshots(self) -> None:
        snapshots = sorted(self.config.snapshot_directory.glob("memory-????-??-??.sqlite"))
        for snapshot in snapshots[: -self.config.daily_snapshots_to_keep]:
            snapshot.unlink()

    def _snapshot_path(self, snapshot_date: date) -> Path:
        return self.config.snapshot_directory / f"memory-{snapshot_date.isoformat()}.sqlite"

    def _remove_database_sidecars(self) -> None:
        for suffix in ("-journal", "-shm", "-wal"):
            Path(f"{self.config.memory_database}{suffix}").unlink(missing_ok=True)

    @staticmethod
    def _temporary_file(directory: Path, prefix: str) -> Path:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, path = tempfile.mkstemp(dir=directory, prefix=f".{prefix}-", suffix=".tmp")
        os.close(descriptor)
        return Path(path)

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Snapshot date must use YYYY-MM-DD") from error
        if parsed.isoformat() != value:
            raise ValueError("Snapshot date must use YYYY-MM-DD")
        return parsed

    @staticmethod
    def _connect_read_only(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _validate_database(cls, path: Path) -> None:
        with cls._connect_read_only(path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if version != MemoryDatabase.schema_version or application != MemoryDatabase.application_id:
            raise ValueError(f"Unsupported memory database snapshot: {path}")
        if integrity != "ok":
            raise ValueError(f"Corrupt memory database snapshot: {path}")
