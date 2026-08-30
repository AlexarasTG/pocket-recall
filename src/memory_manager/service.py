"""Public core operations, independent of persistence and transport."""

from typing import Protocol

from memory_manager.models import MemoryPreSaveDraft, MemoryRecord, SearchCandidate


class MemoryService(Protocol):
    """Core operations, independent of agent sessions and UI types.

    Trusted callers obtain explicit user approval before mutations; an agent
    must not receive an unrestricted write tool. The concrete core validates
    content and limits before persistence. Draft construction is not approval.

    Normal reads expose only active canonical versions, even if a derived
    index is stale. Missing/inactive IDs raise LookupError; invalid content or
    arguments raise ValueError. Storage/index failures must not be hidden as
    empty search results.
    """

    def create(self, draft: MemoryPreSaveDraft) -> MemoryRecord:
        """Persist approved content; created_at and updated_at initially match."""
        ...

    def update(self, memory_id: str, draft: MemoryPreSaveDraft) -> MemoryRecord:
        """Replace approved content, retain the old revision, refresh updated_at."""
        ...

    def delete(self, memory_id: str) -> None:
        """Soft-delete an active record and exclude it from recall immediately."""
        ...

    def restore(self, memory_id: str) -> MemoryRecord:
        """Restore a deleted record within its recovery window and reindex it."""
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
