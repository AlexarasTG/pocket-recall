"""Data structures for memories, archived versions, and search results."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryPreSaveDraft:
    """A proposed memory that can still be edited. It has not been checked or saved."""

    title: str
    body: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryRecord:
    """A memory's saved content and dates. Dates include the UTC time zone."""

    id: str
    title: str
    body: str
    aliases: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchivedMemoryEntry:
    """An older memory version kept for recovery until its expiry date."""

    id: str
    record: MemoryRecord
    retained_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchCandidate:
    """A short search result. Scores compare matches of the same kind, not whether the content is true."""

    id: str
    title: str
    aliases: tuple[str, ...]
    updated_at: datetime
    match_kind: Literal["exact", "lexical", "typo", "semantic"]
    score: float
    excerpt: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchResults:
    """Search results, plus a flag for index updates that may leave some matches missing."""

    candidates: tuple[SearchCandidate, ...]
    index_update_pending: bool
