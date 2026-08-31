"""Define how apps and coding agents can manage and search memories."""

from datetime import datetime
from typing import Protocol

from memory_manager.models import (
    ArchivedMemoryEntry,
    MemoryPreSaveDraft,
    MemoryRecord,
    SearchResults,
)


class MemoryService(Protocol):
    """Operations the memory tool provides, regardless of which app uses it.

    The calling app must get user approval before saving, editing, deleting, or
    restoring a memory. Creating a draft does not count as approval. Agents must
    not get a write tool that skips this check. The implementation checks content
    and limits before saving.

    Normal reads show only current, non-deleted memories, even if the search
    index is out of date. Missing or inactive memories raise MemoryLookupError;
    invalid content or arguments raise ValueError. Database or index errors
    must be reported, not treated as searches with no matches.

    When changing a memory, pass the preview's updated_at as expected_updated_at.
    This prevents overwriting changes made by another session after the preview.
    """

    def create(self, draft: MemoryPreSaveDraft) -> MemoryRecord:
        """Save an approved memory. Set created_at and updated_at to the same time."""
        ...

    def update(
        self,
        memory_id: str,
        draft: MemoryPreSaveDraft,
        *,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        """Save approved changes, keep the previous version, and set updated_at to the edit time."""
        ...

    def delete(
        self,
        memory_id: str,
        *,
        expected_updated_at: datetime | None = None,
    ) -> None:
        """Remove a memory from normal reads and searches, but keep it available for recovery."""
        ...

    def restore(
        self,
        memory_id: str,
        *,
        revision_id: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> MemoryRecord:
        """Bring back a deleted memory or an older version, and request a search-index update."""
        ...

    def history(
        self,
        memory_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ArchivedMemoryEntry, ...]:
        """List older versions that can still be restored, most recently archived first."""
        ...

    def fetch_revision(self, memory_id: str, revision_id: str) -> ArchivedMemoryEntry:
        """Read one archived version so the user can preview it before restoring."""
        ...

    def fetch_deleted(self, memory_id: str) -> MemoryRecord:
        """Read a deleted memory before its recovery deadline, not for normal agent recall."""
        ...

    def list_records(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        """List non-deleted memories for the user to inspect, sorted by ID from lowest to highest."""
        ...

    def list_deleted(self, *, limit: int = 50, offset: int = 0) -> tuple[MemoryRecord, ...]:
        """List deleted memories for recovery, not agent recall. Sort IDs from lowest to highest."""
        ...

    def search(self, query: str) -> SearchResults:
        """Return a limited number of short search results, trying the strongest matches first.

        Try exact titles and aliases, then words and typos, then meaning-based
        matching. Return no candidates if nothing matches. Settings limit how
        many results are returned. Body previews are at most 160 characters and
        stay the same for the same query and content. Only include the full body
        if it fits in the preview. Flag unfinished index updates separately, so
        missing matches are not mistaken for a complete search with no results.
        """
        ...

    def fetch(self, memory_id: str) -> MemoryRecord:
        """Read one selected, non-deleted memory in full. The CLI read ID command uses this too."""
        ...
