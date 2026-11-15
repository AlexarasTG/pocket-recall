"""Store small records of successful searches and full-record fetches."""

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta

from pocket_recall.config import MemoryConfig
from pocket_recall.models import SearchCandidate
from pocket_recall.storage.database import SQLiteDatabase


class RetrievalAuditStore(SQLiteDatabase):
    """Record retrieval measurements and keep their storage within its limits."""

    application_id = 0x50524131
    schema_version = 1
    schema = (
        """CREATE TABLE retrieval_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            operation TEXT NOT NULL,
            query TEXT,
            result_details TEXT NOT NULL,
            returned_characters INTEGER NOT NULL,
            duration_milliseconds REAL NOT NULL
        )""",
        "CREATE INDEX retrieval_events_by_date ON retrieval_events(occurred_at, id)",
        """CREATE TABLE audit_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_age_cleanup_date TEXT
        )""",
        "INSERT INTO audit_state VALUES (1, NULL)",
    )

    def __init__(self, config: MemoryConfig) -> None:
        super().__init__(config.audit_database)
        self.config = config

    def record_search(
        self,
        query: str,
        candidates: tuple[SearchCandidate, ...],
        *,
        returned_characters: int,
        duration_milliseconds: float,
    ) -> None:
        details = [
            {"id": candidate.id, "match_kind": candidate.match_kind, "score": candidate.score}
            for candidate in candidates
        ]
        self._record(
            operation="search",
            query=query,
            result_details=details,
            returned_characters=returned_characters,
            duration_milliseconds=duration_milliseconds,
        )

    def record_fetch(
        self,
        memory_id: str,
        *,
        returned_characters: int,
        duration_milliseconds: float,
    ) -> None:
        self._record(
            operation="fetch",
            query=None,
            result_details=[{"id": memory_id}],
            returned_characters=returned_characters,
            duration_milliseconds=duration_milliseconds,
        )

    def status(self) -> dict[str, object]:
        with self.read() as connection:
            row = connection.execute("""SELECT count(*) AS event_count, min(occurred_at) AS oldest_event_at,
                          max(occurred_at) AS newest_event_at
                   FROM retrieval_events""").fetchone()
        return {
            "database_bytes": self.config.audit_database.stat().st_size,
            "event_count": row["event_count"],
            "oldest_event_at": row["oldest_event_at"],
            "newest_event_at": row["newest_event_at"],
        }

    def empty_results_report(self, keyword: str | None = None) -> dict[str, object]:
        """Summarize retained search terms or the original queries containing one term."""
        if keyword is not None:
            keyword = keyword.casefold().strip()
            if len(keyword.split()) != 1:
                raise ValueError("keyword must be one non-empty whitespace-separated term")
        cutoff = datetime.now(UTC) - timedelta(days=self.config.audit_retention_days)
        with self.read() as connection:
            rows = connection.execute(
                """SELECT occurred_at, query, result_details FROM retrieval_events
                   WHERE operation = 'search' AND occurred_at > ? ORDER BY occurred_at, id""",
                (cutoff.isoformat(),),
            ).fetchall()

        totals: Counter[str] = Counter()
        empty: Counter[str] = Counter()
        for row in rows:
            terms = set(row["query"].casefold().split())
            if keyword is not None:
                if keyword not in terms:
                    continue
                terms = {row["query"]}
            no_results = not json.loads(row["result_details"])
            for term in terms:
                totals[term] += 1
                if no_results:
                    empty[term] += 1

        if keyword is None:
            ranked = sorted(totals, key=lambda term: (-empty[term], -totals[term], term))
            ranked = ranked[: self.config.audit_report_keyword_limit]
        else:
            ranked = sorted(totals, key=lambda term: (-totals[term], term))
        label = "keyword" if keyword is None else "query"
        return {
            "oldest_search_at": rows[0]["occurred_at"] if rows else None,
            "newest_search_at": rows[-1]["occurred_at"] if rows else None,
            "keyword": keyword,
            "results": [
                {label: term, "total_searches": totals[term], "empty_searches": empty[term]} for term in ranked
            ],
        }

    def searched_memory_ids(self) -> tuple[str | None, frozenset[str]]:
        """Return the oldest retained search date and the IDs that appeared in search results since then."""
        cutoff = datetime.now(UTC) - timedelta(days=self.config.audit_retention_days)
        with self.read() as connection:
            oldest = connection.execute(
                "SELECT min(occurred_at) FROM retrieval_events WHERE operation = 'search' AND occurred_at > ?",
                (cutoff.isoformat(),),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT DISTINCT json_extract(r.value, '$.id') FROM retrieval_events AS e, json_each(e.result_details) AS r
                   WHERE e.operation = 'search' AND e.occurred_at > ?""",
                (cutoff.isoformat(),),
            ).fetchall()
        return oldest, frozenset(row[0] for row in rows)

    def _record(
        self,
        *,
        operation: str,
        query: str | None,
        result_details: list[dict[str, object]],
        returned_characters: int,
        duration_milliseconds: float,
    ) -> None:
        now = datetime.now(UTC)
        with self.write() as connection:
            last_cleanup = connection.execute("SELECT last_age_cleanup_date FROM audit_state WHERE id = 1").fetchone()[
                0
            ]
            if last_cleanup != now.date().isoformat():
                cutoff = now - timedelta(days=self.config.audit_retention_days)
                connection.execute("DELETE FROM retrieval_events WHERE occurred_at <= ?", (cutoff.isoformat(),))
                connection.execute(
                    "UPDATE audit_state SET last_age_cleanup_date = ? WHERE id = 1", (now.date().isoformat(),)
                )
            connection.execute(
                """INSERT INTO retrieval_events (
                       occurred_at, operation, query, result_details,
                       returned_characters, duration_milliseconds
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    now.isoformat(),
                    operation,
                    query,
                    json.dumps(result_details, ensure_ascii=True, separators=(",", ":")),
                    returned_characters,
                    duration_milliseconds,
                ),
            )
        if self.config.audit_database.stat().st_size >= self.config.audit_max_bytes:
            self._trim_to_target()

    def _trim_to_target(self) -> None:
        with self.write() as connection:
            while self._used_bytes(connection) > self.config.audit_trim_target_bytes:
                event_count = connection.execute("SELECT count(*) FROM retrieval_events").fetchone()[0]
                if event_count == 0:
                    break
                batch_size = max(1, min(100, event_count // 10))
                connection.execute(
                    "DELETE FROM retrieval_events WHERE id IN "
                    "(SELECT id FROM retrieval_events ORDER BY occurred_at, id LIMIT ?)",
                    (batch_size,),
                )
        with self._connect() as connection:
            connection.execute("VACUUM")

    @staticmethod
    def _used_bytes(connection: sqlite3.Connection) -> int:
        page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        return (page_count - free_pages) * page_size
