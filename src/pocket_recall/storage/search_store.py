"""Store search-index data in SQLite and run the queries used to find matches."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import numpy as np

from pocket_recall.config import MemoryConfig
from pocket_recall.models import MemoryRecord
from pocket_recall.retrieval.search_text_processing import (
    MAX_TYPO_ALTERNATIVES,
    MIN_TYPO_WORD_LENGTH,
    excerpt_marker,
    is_one_typo_away,
    normalize_exact,
    words,
)
from pocket_recall.storage.database import MemoryDatabase, SQLiteDatabase


class SearchStore(SQLiteDatabase):
    """Read and write the search index, including its tables and SQL queries.

    Return database matches for the search coordinator to use. Exclude deleted or
    outdated versions. This index can be rebuilt from the saved memories.
    """

    application_id = 0x4D534931
    schema_version = 2
    schema = (
        "CREATE TABLE index_state (id INTEGER PRIMARY KEY CHECK (id = 1), ready INTEGER NOT NULL)",
        "INSERT INTO index_state VALUES (1, 0)",
        "CREATE TABLE indexed_memories (memory_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL)",
        """CREATE TABLE exact_terms (
            term TEXT NOT NULL,
            memory_id TEXT NOT NULL REFERENCES indexed_memories(memory_id) ON DELETE CASCADE,
            PRIMARY KEY (term, memory_id)
        )""",
        "CREATE INDEX exact_terms_by_memory ON exact_terms(memory_id)",
        """CREATE VIRTUAL TABLE memory_text USING fts5(
            title, aliases, body, tokenize = 'porter unicode61 remove_diacritics 0'
        )""",
        """CREATE TABLE search_words (
            word TEXT NOT NULL,
            word_length INTEGER NOT NULL,
            memory_id TEXT NOT NULL REFERENCES indexed_memories(memory_id) ON DELETE CASCADE,
            PRIMARY KEY (word, memory_id)
        )""",
        "CREATE INDEX search_words_by_length ON search_words(word_length, word)",
        "CREATE INDEX search_words_by_memory ON search_words(memory_id)",
    )

    def __init__(self, path: Path, specification: str, dimensions: int) -> None:
        super().__init__(path)
        self.specification = specification
        self.dimensions = dimensions
        self.vector_schema = (
            "CREATE TABLE embedding_metadata (id INTEGER PRIMARY KEY CHECK (id = 1), specification TEXT NOT NULL)",
            f"""CREATE TABLE memory_vectors (
                memory_id TEXT PRIMARY KEY REFERENCES indexed_memories(memory_id) ON DELETE CASCADE,
                embedding BLOB NOT NULL CHECK (length(embedding) = {dimensions * 4})
            )""",
        )
        self.schema = type(self).schema + self.vector_schema

    def initialize(self) -> None:
        if self.path.is_file():
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                application = connection.execute("PRAGMA application_id").fetchone()[0]
                if version == 1 and application == self.application_id:
                    for statement in self.vector_schema:
                        connection.execute(statement)
                    connection.execute("UPDATE index_state SET ready = 0 WHERE id = 1")
                    connection.execute(f"PRAGMA user_version = {self.schema_version}")
        super().initialize()

    def is_ready(self, connection: sqlite3.Connection, *, schema: str = "main") -> bool:
        row = connection.execute(f"""SELECT s.ready, e.specification FROM {schema}.index_state AS s
                LEFT JOIN {schema}.embedding_metadata AS e ON e.id = s.id WHERE s.id = 1""").fetchone()
        return bool(row and row["ready"] and row["specification"] == self.specification)

    def mark_ready(self, connection: sqlite3.Connection) -> None:
        connection.execute("INSERT OR REPLACE INTO embedding_metadata VALUES (1, ?)", (self.specification,))
        connection.execute("UPDATE index_state SET ready = 1 WHERE id = 1")

    @contextmanager
    def snapshot(self, database: MemoryDatabase) -> Iterator[sqlite3.Connection]:
        with database.read() as connection:
            connection.create_function("excerpt_marker", 1, excerpt_marker, deterministic=True)
            connection.execute("ATTACH DATABASE ? AS search", (self.path.as_uri() + "?mode=ro",))
            version = connection.execute("PRAGMA search.user_version").fetchone()[0]
            application = connection.execute("PRAGMA search.application_id").fetchone()[0]
            if version != self.schema_version or application != self.application_id:
                raise ValueError("Unsupported search index; rebuild it with memory maintenance reindex")
            connection.execute("BEGIN")
            # Pin canonical state before reading the independently committed index.
            connection.execute("SELECT count(*) FROM memories").fetchone()
            if not self.is_ready(connection, schema="search"):
                raise ValueError("Search index is not ready for this model; run memory maintenance reindex")
            yield connection

    def remove(self, connection: sqlite3.Connection, memory_id: str) -> None:
        connection.execute(
            "DELETE FROM memory_text WHERE rowid = (SELECT rowid FROM indexed_memories WHERE memory_id = ?)",
            (memory_id,),
        )
        connection.execute("DELETE FROM indexed_memories WHERE memory_id = ?", (memory_id,))

    def replace(self, connection: sqlite3.Connection, record: MemoryRecord, embedding: bytes) -> None:
        self.remove(connection, record.id)
        cursor = connection.execute(
            "INSERT INTO indexed_memories (memory_id, updated_at) VALUES (?, ?)",
            (record.id, record.updated_at.isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_text (rowid, title, aliases, body) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, record.title, " ".join(record.aliases), record.body),
        )
        connection.executemany(
            "INSERT INTO exact_terms (term, memory_id) VALUES (?, ?)",
            [(term, record.id) for term in sorted({normalize_exact(text) for text in (record.title, *record.aliases)})],
        )
        connection.executemany(
            "INSERT INTO search_words (word, word_length, memory_id) VALUES (?, ?, ?)",
            [(word, len(word), record.id) for word in words(" ".join((record.title, *record.aliases, record.body)))],
        )
        connection.execute("INSERT INTO memory_vectors VALUES (?, ?)", (record.id, embedding))

    def clear(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM memory_text")
        connection.execute("DELETE FROM indexed_memories")
        connection.execute("DROP TABLE memory_vectors")
        connection.execute(self.vector_schema[1])

    def has_pending_updates(self, connection: sqlite3.Connection) -> bool:
        return bool(connection.execute("""SELECT EXISTS(SELECT 1 FROM pending_index_updates)
                OR EXISTS(
                    SELECT 1 FROM memories AS m
                    LEFT JOIN search.indexed_memories AS i
                        ON i.memory_id = m.id AND i.updated_at = m.updated_at
                    LEFT JOIN search.memory_vectors AS v ON v.memory_id = i.memory_id
                    WHERE m.deleted_at IS NULL AND (i.memory_id IS NULL OR v.memory_id IS NULL)
                )""").fetchone()[0])

    def exact_matches(self, connection: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT m.*, i.rowid AS indexed_rowid
               FROM search.exact_terms AS e
               JOIN search.indexed_memories AS i ON i.memory_id = e.memory_id
               JOIN search.memory_vectors AS v ON v.memory_id = i.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE e.term = ? AND m.deleted_at IS NULL
               ORDER BY m.id LIMIT ?""",
            (normalize_exact(query), limit),
        ).fetchall()

    def keyword_matches(
        self,
        connection: sqlite3.Connection,
        expression: str,
        config: MemoryConfig,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT m.*, -bm25(memory_text, ?, ?, ?) AS score,
                      highlight(memory_text, 2, excerpt_marker(memory_text.body),
                                excerpt_marker(memory_text.body)) AS highlighted_body
               FROM search.memory_text
               JOIN search.indexed_memories AS i ON i.rowid = memory_text.rowid
               JOIN search.memory_vectors AS v ON v.memory_id = i.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE memory_text MATCH ? AND m.deleted_at IS NULL
               ORDER BY score DESC, m.id LIMIT ?""",
            (
                config.title_alias_search_weight,
                config.title_alias_search_weight,
                config.body_search_weight,
                expression,
                config.max_candidates_per_search,
            ),
        ).fetchall()

    def highlighted_body(self, connection: sqlite3.Connection, rowid: int, expression: str) -> str | None:
        row = connection.execute(
            """SELECT highlight(memory_text, 2, excerpt_marker(body), excerpt_marker(body))
               FROM search.memory_text
               WHERE rowid = ? AND memory_text MATCH ?""",
            (rowid, expression),
        ).fetchone()
        return row[0] if row else None

    def semantic_matches(
        self,
        connection: sqlite3.Connection,
        query_embedding: bytes,
        *,
        threshold: float,
        limit: int,
        excluded_ids: tuple[str, ...] = (),
    ) -> tuple[tuple[sqlite3.Row, float], ...]:
        """Compare current vectors in small batches, then read only the winning records."""
        query_vector = np.frombuffer(query_embedding, dtype="<f4")
        if query_vector.shape != (self.dimensions,) or not np.isfinite(query_vector).all():
            raise ValueError("Invalid query vector")
        cursor = connection.execute("""SELECT v.memory_id, v.embedding FROM search.memory_vectors AS v
               JOIN search.indexed_memories AS i ON i.memory_id = v.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE m.deleted_at IS NULL ORDER BY v.memory_id""")
        best: list[tuple[str, float]] = []
        while batch := cursor.fetchmany(256):
            vectors = np.frombuffer(b"".join(row["embedding"] for row in batch), dtype="<f4")
            if vectors.size != len(batch) * self.dimensions or not np.isfinite(vectors).all():
                raise ValueError("Invalid stored vectors; run memory maintenance reindex")
            # Dot products of normalized vectors give cosine similarity.
            scores = np.clip(np.einsum("ij,j->i", vectors.reshape(-1, self.dimensions), query_vector), -1, 1)
            best.extend(
                (row["memory_id"], float(score))
                for row, score in zip(batch, scores)
                if score >= threshold and row["memory_id"] not in excluded_ids
            )
            best.sort(key=lambda match: (-match[1], match[0]))
            del best[limit:]
        return tuple(
            (connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone(), score)
            for memory_id, score in best
        )

    def similar_pairs(
        self, connection: sqlite3.Connection, *, threshold: float, limit: int
    ) -> tuple[tuple[str, str, float], ...]:
        """Return the most similar pairs of current memories, compared in small batches."""
        rows = connection.execute("""SELECT v.memory_id, v.embedding FROM search.memory_vectors AS v
               JOIN search.indexed_memories AS i ON i.memory_id = v.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE m.deleted_at IS NULL ORDER BY v.memory_id""").fetchall()
        if len(rows) < 2:
            return ()
        vectors = np.frombuffer(b"".join(row["embedding"] for row in rows), dtype="<f4").reshape(-1, self.dimensions)
        best: list[tuple[str, str, float]] = []
        for start in range(0, len(rows), 256):
            scores = np.clip(vectors[start : start + 256] @ vectors.T, -1, 1)
            for offset, row_scores in enumerate(scores):
                left = start + offset
                for right in np.flatnonzero(row_scores[left + 1 :] >= threshold) + left + 1:
                    best.append((rows[left]["memory_id"], rows[right]["memory_id"], float(row_scores[right])))
            best.sort(key=lambda pair: (-pair[2], pair[0], pair[1]))
            del best[limit:]
        return tuple(best)

    def has_current_vectors(self, connection: sqlite3.Connection) -> bool:
        return bool(connection.execute("""SELECT EXISTS(SELECT 1 FROM search.memory_vectors AS v
               JOIN search.indexed_memories AS i ON i.memory_id = v.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE m.deleted_at IS NULL)""").fetchone()[0])

    def spelling_options(self, connection: sqlite3.Connection, term: str) -> tuple[str, ...]:
        if len(term) < MIN_TYPO_WORD_LENGTH or not term.isalpha():
            return (term,)
        rows = connection.execute(
            """SELECT DISTINCT w.word FROM search.search_words AS w
               JOIN search.indexed_memories AS i ON i.memory_id = w.memory_id
               JOIN search.memory_vectors AS v ON v.memory_id = i.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE w.word_length BETWEEN ? AND ? AND m.deleted_at IS NULL
               ORDER BY w.word""",
            (max(MIN_TYPO_WORD_LENGTH, len(term) - 1), len(term) + 1),
        )
        alternatives = [term]
        for row in rows:
            candidate = row[0]
            if candidate.isalpha() and is_one_typo_away(term, candidate):
                alternatives.append(candidate)
                if len(alternatives) == MAX_TYPO_ALTERNATIVES + 1:
                    break
        return tuple(alternatives)
