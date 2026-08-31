"""Transport-independent values shared by the core and its clients."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryPreSaveDraft:
    """User-editable content, not yet validated or persisted."""

    title: str
    body: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRecord:
    """Canonical record. Persisted timestamps are timezone-aware UTC."""

    id: str
    title: str
    body: str
    aliases: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchivedMemoryEntry:
    """An archived version that can be restored before its expiry date."""

    id: str
    record: MemoryRecord
    retained_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchCandidate:
    """Compact recall result; scores rank within a tier, not factual truth."""

    id: str
    title: str
    aliases: tuple[str, ...]
    updated_at: datetime
    match_kind: Literal["exact", "lexical", "semantic"]
    score: float
    excerpt: str = ""
