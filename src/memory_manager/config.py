"""Settings for paths, search, and storage. Creating these settings starts nothing and creates no files."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryConfig:
    """Settings used by the memory tool and the apps that connect to it.

    Workspace roots tell apps where to enable automatic memory use. An empty
    list disables it. These paths do not affect which search results rank higher.
    Use full filesystem paths, with shortcuts such as ~ already expanded.
    """

    RECORD_BODY_CHARACTER_LIMIT: ClassVar[int] = 1_000
    SEARCH_PREVIEW_CHARACTER_LIMIT: ClassVar[int] = 160

    data_directory: Path
    enabled_workspace_roots: tuple[Path, ...] = ()
    max_candidates_per_search: int = 5
    max_fetch_records_per_subproblem: int = 3
    max_searches_per_subproblem: int = 3
    title_alias_search_weight: float = 5.0
    body_search_weight: float = 1.0
    typo_matching_enabled: bool = True
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
        for name in ("title_alias_search_weight", "body_search_weight"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")

    @property
    def memory_database(self) -> Path:
        return self.data_directory / "memory.sqlite"

    @property
    def search_database(self) -> Path:
        return self.data_directory / "search-index.sqlite"

    @property
    def audit_database(self) -> Path:
        return self.data_directory / "audit.sqlite"
