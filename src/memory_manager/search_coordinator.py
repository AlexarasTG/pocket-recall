"""Control the search flow and turn database matches into short results."""

import sqlite3
from typing import Literal

from memory_manager.archived_memory_store import record_from_row
from memory_manager.config import MemoryConfig
from memory_manager.database import MemoryDatabase
from memory_manager.models import SearchCandidate, SearchResults
from memory_manager.search_store import SearchStore
from memory_manager.search_text_processing import (
    body_excerpt,
    keyword_expression,
    query_terms,
)


class SearchCoordinator:
    """Decide which matching method to try and what to return to the caller.

    Try exact matches, then keywords, then typos. Ask SearchStore for the
    database matches and turn them into short previews with indexing status.
    """

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self.database = MemoryDatabase(config.memory_database)
        self.index = SearchStore(config.search_database)

    def search(self, query: str) -> SearchResults:
        terms = query_terms(query)
        expression = keyword_expression(tuple((term,) for term in terms))
        with self.index.snapshot(self.database) as connection:
            pending = self.index.has_pending_updates(connection)
            candidates = self._search(connection, query, terms, expression)
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
        kind: Literal["exact", "lexical", "typo"],
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
