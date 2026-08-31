"""Public core operations, independent of persistence and transport."""

from datetime import datetime
from typing import Protocol

from memory_manager.models import MemoryPreSaveDraft, MemoryRecord, ArchivedMemoryEntry, SearchCandidate


class MemoryService(Protocol):
    """Core operations, independent of agent sessions and UI types.

    Trusted callers obtain explicit user approval before mutations; an agent
    must not receive an unrestricted write tool. The concrete core validates
    content and limits before persistence. Draft construction is not approval.

    Normal reads expose only active canonical versions, even if a derived
    index is stale. Missing/inactive IDs raise LookupError; invalid content or
    arguments raise ValueError. Storage/index failures must not be hidden as
    empty search results.

    Pass the previewed record's updated_at to mutations so another session's
    edits cannot be overwritten by an approval based on older content.
    """

    def create(self, draft: MemoryPreSaveDraft) -> MemoryRecord:
        """Persist approved content; created_at and updated_at initially match."""
        ...

    def update(
        self, memory_id: str, draft: MemoryPreSaveDraft,
        *, expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        """Replace approved content, retain the old revision, refresh updated_at."""
        ...

    def delete(
        self, memory_id: str, *, expected_updated_at: datetime | None = None,
    ) -> None:
        """Soft-delete an active record and exclude it from recall immediately."""
        ...

    def restore(
        self, memory_id: str, *, revision_id: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        """Restore deleted or historical content and request an index update."""
        ...

    def history(
        self, memory_id: str, *, limit: int = 50, offset: int = 0,
    ) -> tuple[ArchivedMemoryEntry, ...]:
        """List recoverable versions, newest replacement first."""
        ...

    def fetch_revision(self, memory_id: str, revision_id: str) -> ArchivedMemoryEntry:
        """Read one retained version for an explicit recovery preview."""
        ...

    def fetch_deleted(self, memory_id: str) -> MemoryRecord:
        """Read a deleted record within its recovery window; not for recall."""
        ...

    def list_records(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[MemoryRecord, ...]:
        """List active records for human inspection, ordered by ID ascending."""
        ...

    def list_deleted(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[MemoryRecord, ...]:
        """Explicit recovery-only listing, ordered by ID ascending; not recall."""
        ...

    def search(self, query: str) -> tuple[SearchCandidate, ...]:
        """Return capped candidates through exact, lexical, then vector fallback.

        Excerpts are deterministic and at most 160 characters. No match returns
        an empty tuple. Full bodies are not returned except when they fit in
        the excerpt. Candidate count is bounded by configuration.
        """
        ...

    def fetch(self, memory_id: str) -> MemoryRecord:
        """Read one selected active record; CLI show uses this same operation."""
        ...
