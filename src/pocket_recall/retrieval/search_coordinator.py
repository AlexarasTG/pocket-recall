"""Control the search flow and turn database matches into short results."""

import sqlite3
from typing import Literal

from pocket_recall.config import MemoryConfig
from pocket_recall.embeddings.model_lifecycle_manager import ModelLifecycleManager
from pocket_recall.models import SearchCandidate, SearchResults
from pocket_recall.retrieval.search_text_processing import (
    body_excerpt,
    keyword_expression,
    query_terms,
)
from pocket_recall.storage.archived_memory_store import record_from_row
from pocket_recall.storage.database import MemoryDatabase
from pocket_recall.storage.search_store import SearchStore


class SearchCoordinator:
    """Decide which matching method to try and what to return to the caller.

    Try exact matches, then keywords, then typos and semantic fallback. Ask SearchStore for the
    database matches and turn them into short previews with indexing status.
    """

    def __init__(
        self,
        config: MemoryConfig,
        database: MemoryDatabase,
        index: SearchStore,
        model_lifecycle_manager: ModelLifecycleManager,
    ) -> None:
        self.config = config
        self.database = database
        self.index = index
        self.model_lifecycle_manager = model_lifecycle_manager

    def search(self, query: str) -> SearchResults:
        terms = query_terms(query)
        expression = keyword_expression(tuple((term,) for term in terms))
        with self.index.snapshot(self.database) as connection:
            pending = self.index.has_pending_updates(connection)
            candidates = self._search(connection, query, terms, expression)
            remaining = self.config.max_candidates_per_search - len(candidates)
            use_semantic = not candidates or self.config.semantic_fallback_policy == "fill_remaining_slots"
            if terms and remaining > 0 and use_semantic and self.index.has_current_vectors(connection):
                embedding = self.model_lifecycle_manager.embed_query(query)
                matches = self.index.semantic_matches(
                    connection,
                    embedding,
                    threshold=self.config.semantic_similarity_threshold,
                    limit=remaining,
                    excluded_ids=tuple(candidate.id for candidate in candidates),
                )
                candidates += tuple(self._candidate(row, "semantic", score, None) for row, score in matches)
            return SearchResults(candidates=candidates, index_update_pending=pending)

    def _search(
        self,
        connection: sqlite3.Connection,
        query: str,
        terms: tuple[str, ...],
        expression: str,
    ) -> tuple[SearchCandidate, ...]:
        exact = self.index.exact_matches(connection, query, self.config.max_candidates_per_search)
        if exact:
            return tuple(
                self._candidate(
                    row,
                    "exact",
                    1.0,
                    self.index.highlighted_body(connection, row["indexed_rowid"], expression) if terms else None,
                )
                for row in exact
            )
        if not terms:
            return ()
        matches = self.index.keyword_matches(connection, expression, self.config)
        if matches:
            return tuple(self._candidate(row, "lexical", row["score"], row["highlighted_body"]) for row in matches)
        if self.config.typo_matching_enabled:
            options = tuple(self.index.spelling_options(connection, term) for term in terms)
            if any(len(alternatives) > 1 for alternatives in options):
                matches = self.index.keyword_matches(connection, keyword_expression(options), self.config)
                return tuple(self._candidate(row, "typo", row["score"], row["highlighted_body"]) for row in matches)
        return ()

    def _candidate(
        self,
        row: sqlite3.Row,
        kind: Literal["exact", "lexical", "typo", "semantic"],
        score: float,
        highlighted_body: str | None,
    ) -> SearchCandidate:
        record = record_from_row(row)
        return SearchCandidate(
            id=record.id,
            title=record.title,
            aliases=record.aliases,
            updated_at=record.updated_at,
            match_kind=kind,
            score=score,
            excerpt=body_excerpt(record.body, highlighted_body, self.config.SEARCH_PREVIEW_CHARACTER_LIMIT),
        )
