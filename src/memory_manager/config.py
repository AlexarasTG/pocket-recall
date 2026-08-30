"""Explicit local configuration; constructing it creates no files or processes."""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryConfig:
    """Workspace roots control client activation, never search ranking.

    Clients treat an empty allowlist as disabled. Callers must supply absolute
    paths with home-directory shortcuts already expanded.
    """

    RECORD_BODY_TOKEN_LIMIT: ClassVar[int] = 250
    SEARCH_PREVIEW_CHARACTER_LIMIT: ClassVar[int] = 160

    data_directory: Path
    enabled_workspace_roots: tuple[Path, ...] = ()
    max_candidates_per_search: int = 5
    max_fetch_records_per_subproblem: int = 3
    max_searches_per_subproblem: int = 3
    recovery_retention_days: int = 60
    audit_retention_days: int = 30
    audit_max_bytes: int = 100_000_000
    daily_snapshots_to_keep: int = 7
    model_idle_timeout_minutes: int = 60

    def __post_init__(self) -> None:
        for path in (self.data_directory, *self.enabled_workspace_roots):
            if not path.is_absolute():
                raise ValueError(f"Configuration paths must be absolute: {path}")

        positive_limits = (
            "max_candidates_per_search",
            "max_fetch_records_per_subproblem",
            "max_searches_per_subproblem",
            "recovery_retention_days",
            "audit_retention_days",
            "audit_max_bytes",
            "daily_snapshots_to_keep",
            "model_idle_timeout_minutes",
        )
        for name in positive_limits:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def memory_database(self) -> Path:
        return self.data_directory / "memory.sqlite"

    @property
    def search_database(self) -> Path:
        return self.data_directory / "search-index.sqlite"

    @property
    def audit_database(self) -> Path:
        return self.data_directory / "audit.sqlite"
