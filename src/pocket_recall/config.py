"""Settings for paths, search, and storage. Creating these settings starts nothing and creates no files."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import ClassVar, Literal

DEFAULT_DATA_DIRECTORY = Path.home() / ".local" / "share" / "pocket-recall"


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryConfig:
    """Settings used by the memory tool and the apps that connect to it.

    Workspace roots tell apps where to enable automatic memory use. An empty
    list disables it. These paths do not affect which search results rank higher.
    Use full filesystem paths, with shortcuts such as ~ already expanded.
    """

    RECORD_BODY_CHARACTER_LIMIT: ClassVar[int] = 1_000
    SEARCH_PREVIEW_CHARACTER_LIMIT: ClassVar[int] = 160

    data_directory: Path = DEFAULT_DATA_DIRECTORY
    enabled_workspace_roots: tuple[Path, ...] = ()
    max_candidates_per_search: int = 5
    max_fetch_records_per_subproblem: int = 3
    max_searches_per_subproblem: int = 3
    title_alias_search_weight: float = 5.0
    body_search_weight: float = 1.0
    typo_matching_enabled: bool = True
    semantic_fallback_policy: Literal["on_zero_results", "fill_remaining_slots"] = "on_zero_results"
    semantic_similarity_threshold: float = 0.65
    embedding_threads: int = 2
    recovery_retention_days: int = 60
    audit_retention_days: int = 30
    audit_max_bytes: int = 10_000_000
    audit_trim_target_bytes: int = 8_000_000
    daily_snapshots_to_keep: int = 7
    model_idle_timeout_minutes: int = 60
    max_concurrent_requests: int = 16
    socket_startup_timeout_seconds: int = 5
    normal_request_timeout_seconds: int = 30
    maintenance_request_timeout_seconds: int = 300
    max_socket_request_bytes: int = 65_536
    index_retry_delays_seconds: tuple[int, ...] = (5, 30, 120, 600)

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
            "audit_trim_target_bytes",
            "daily_snapshots_to_keep",
            "model_idle_timeout_minutes",
            "embedding_threads",
            "max_concurrent_requests",
            "socket_startup_timeout_seconds",
            "normal_request_timeout_seconds",
            "maintenance_request_timeout_seconds",
            "max_socket_request_bytes",
        )
        for name in positive_limits:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("title_alias_search_weight", "body_search_weight"):
            value = getattr(self, name)
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.semantic_fallback_policy not in ("on_zero_results", "fill_remaining_slots"):
            raise ValueError("Semantic fallback policy must be on_zero_results or fill_remaining_slots")
        if not isfinite(self.semantic_similarity_threshold) or not -1 <= self.semantic_similarity_threshold <= 1:
            raise ValueError("Semantic similarity threshold must be between -1 and 1")
        if len(self.index_retry_delays_seconds) != 4 or any(delay <= 0 for delay in self.index_retry_delays_seconds):
            raise ValueError("Index retry delays must contain four positive values")
        if self.audit_trim_target_bytes >= self.audit_max_bytes:
            raise ValueError("Audit trim target must be smaller than the audit size limit")

    @property
    def model_directory(self) -> Path:
        return self.data_directory / "models"

    @property
    def memory_database(self) -> Path:
        return self.data_directory / "memory.sqlite"

    @property
    def search_database(self) -> Path:
        return self.data_directory / "search-index.sqlite"

    @property
    def audit_database(self) -> Path:
        return self.data_directory / "audit.sqlite"

    @property
    def snapshot_directory(self) -> Path:
        return self.data_directory / "snapshots"

    @property
    def database_before_restore(self) -> Path:
        return self.data_directory / "memory-before-restore.sqlite"

    @property
    def service_socket(self) -> Path:
        return self.data_directory / "service.sock"

    @property
    def service_lock(self) -> Path:
        return self.data_directory / "service.lock"

    @property
    def service_log(self) -> Path:
        return self.data_directory / "service.log"
