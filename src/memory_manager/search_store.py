"""Store search-index data in SQLite and run the queries used to find matches."""

from contextlib import contextmanager
import sqlite3
from typing import Iterator

from memory_manager.config import MemoryConfig
from memory_manager.database import MemoryDatabase, SQLiteDatabase
from memory_manager.models import MemoryRecord
from memory_manager.search_text_processing import (
    MAX_TYPO_ALTERNATIVES, MIN_TYPO_WORD_LENGTH,
    excerpt_marker, is_one_typo_away, normalize_exact, words,
)


class SearchStore(SQLiteDatabase):
    """Read and write the search index, including its tables and SQL queries.

    Return database matches for the search coordinator to use. Exclude deleted or
    outdated versions. This index can be rebuilt from the saved memories.
    """

    application_id = 0x4D534931
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
            if not connection.execute("SELECT ready FROM search.index_state WHERE id = 1").fetchone()[0]:
                raise ValueError("Search index is not ready; run memory maintenance reindex")
            yield connection

    def remove(self, connection: sqlite3.Connection, memory_id: str) -> None:
        connection.execute(
            "DELETE FROM memory_text WHERE rowid = (SELECT rowid FROM indexed_memories WHERE memory_id = ?)",
            (memory_id,),
        )
        connection.execute("DELETE FROM indexed_memories WHERE memory_id = ?", (memory_id,))

    def replace(self, connection: sqlite3.Connection, record: MemoryRecord) -> None:
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

    def clear(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM memory_text")
        connection.execute("DELETE FROM indexed_memories")

    def has_pending_updates(self, connection: sqlite3.Connection) -> bool:
        return bool(connection.execute(
            """SELECT EXISTS(SELECT 1 FROM pending_index_updates)
                OR EXISTS(
                    SELECT 1 FROM memories AS m
                    LEFT JOIN search.indexed_memories AS i
                        ON i.memory_id = m.id AND i.updated_at = m.updated_at
                    WHERE m.deleted_at IS NULL AND i.memory_id IS NULL
                )"""
        ).fetchone()[0])

    def exact_matches(self, connection: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT m.*, i.rowid AS indexed_rowid
               FROM search.exact_terms AS e
               JOIN search.indexed_memories AS i ON i.memory_id = e.memory_id
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE e.term = ? AND m.deleted_at IS NULL
               ORDER BY m.id LIMIT ?""",
            (normalize_exact(query), limit),
        ).fetchall()

    def keyword_matches(
        self, connection: sqlite3.Connection, expression: str, config: MemoryConfig,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT m.*, -bm25(memory_text, ?, ?, ?) AS score,
                      highlight(memory_text, 2, excerpt_marker(memory_text.body),
                                excerpt_marker(memory_text.body)) AS highlighted_body
               FROM search.memory_text
               JOIN search.indexed_memories AS i ON i.rowid = memory_text.rowid
               JOIN memories AS m ON m.id = i.memory_id AND m.updated_at = i.updated_at
               WHERE memory_text MATCH ? AND m.deleted_at IS NULL
               ORDER BY score DESC, m.id LIMIT ?""",
            (
                config.title_alias_search_weight, config.title_alias_search_weight,
                config.body_search_weight,
                expression, config.max_candidates_per_search,
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

    def spelling_options(self, connection: sqlite3.Connection, term: str) -> tuple[str, ...]:
        if len(term) < MIN_TYPO_WORD_LENGTH or not term.isalpha():
            return (term,)
        rows = connection.execute(
            """SELECT DISTINCT w.word FROM search.search_words AS w
               JOIN search.indexed_memories AS i ON i.memory_id = w.memory_id
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
