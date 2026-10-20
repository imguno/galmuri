"""Bounded candidate pages with current permissions and source-intent fences."""

import json
from contextlib import closing

from galmuri.documents.lexical.analyzer import (
    MAX_QUERY_CHARACTERS,
    MAX_QUERY_TERMS,
    VERSION,
    query_terms,
)
from galmuri.documents.lexical.ranking import K1, B, statement


class LexicalIndex:
    def __init__(self, database, *, revision=None):
        self.database = database
        self.revision = revision

    def _check_revision(self, connection, app):
        if self.revision is None:
            return
        state = connection.execute("SELECT revision FROM app_state WHERE name=?", (app,)).fetchone()
        if state is None or state["revision"] != self.revision:
            raise ValueError("App revision is no longer active; reload the runtime")

    def search(self, app, query, principal, limit=20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        terms = query_terms(query)
        if not terms:
            return []
        selected = []
        page_size = min(256, max(32, limit))
        # A snapshot keeps ranking and pagination stable. Only candidate headers
        # cross this boundary; accepted bodies are fetched under a fresh fence.
        with self.database.snapshot() as connection:
            self._check_revision(connection, app)
            ranked = statement(connection, app, terms)
            if ranked is None:
                return []
            sql, parameters = ranked
            stream = getattr(connection, "stream", None)
            cursor_context = (
                stream(sql, parameters)
                if callable(stream)
                else closing(connection.execute(sql, parameters))
            )
            with cursor_context as cursor:
                while len(selected) < limit:
                    page = cursor.fetchmany(page_size)
                    for candidate in page:
                        if not principal.matches(json.loads(candidate["readers"])):
                            continue
                        selected.append(dict(candidate))
                        if len(selected) == limit:
                            break
                    if len(page) < page_size:
                        break
        return self._fetch(app, selected, principal)

    def _fetch(self, app, selected, principal):
        from galmuri.documents.queries import serialize

        current = {}
        with self.database.snapshot() as connection:
            self._check_revision(connection, app)
            for start in range(0, len(selected), 256):
                keys = tuple(item["key"] for item in selected[start : start + 256])
                placeholders = ",".join("?" for _ in keys)
                rows = connection.execute(
                    "SELECT d.*,a.revision FROM documents d "
                    "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
                    "JOIN app_state a ON a.name=d.app "
                    f"WHERE d.app=? AND d.key IN ({placeholders}) AND d.state='ACTIVE' "
                    "AND s.deleted=0 AND s.version=d.version",
                    (app, *keys),
                ).fetchall()
                current.update(
                    (row["key"], row)
                    for row in rows
                    if principal.matches(json.loads(row["readers"]))
                )
        return [
            serialize(current[item["key"]]) | {"score": float(item["score"])}
            for item in selected
            if item["key"] in current
            and all(
                current[item["key"]][field] == item[field]
                for field in ("version", "source_key", "revision")
            )
        ]

    @staticmethod
    def describe():
        return {
            "method": "lexical",
            "index": "transactional inverted postings",
            "query": (
                "all word and single-Hangul terms, plus at least half of distinct Hangul "
                "bigrams rounded up; blank and punctuation-only queries return no hits"
            ),
            "score": "BM25",
            "bm25": {"k1": K1, "b": B},
            "analyzer": VERSION,
            "normalization": "Unicode NFKC and casefold; word identifiers preserve underscores",
            "korean": "Hangul bigrams across whitespace; approximate, not morphology",
            "limit": {"default": 20, "maximum": 1000},
            "query_limits": {"characters": MAX_QUERY_CHARACTERS, "terms": MAX_QUERY_TERMS},
        }
