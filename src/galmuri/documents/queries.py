"""Query current publication with current ACLs before returning any document data."""

import json


def serialize(row):
    return {
        "key": row["key"],
        "text": row["text"],
        "metadata": json.loads(row["metadata"]),
        "version": row["version"],
        "source_key": row["source_key"],
    }


class Queries:
    def __init__(self, database):
        self.database = database

    def list_documents(self, app, principal, **options):
        from galmuri.documents.inventory import listing

        return listing(self.database, app, principal, **options)

    def read(self, app, key, principal):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE app=? AND key=? AND state='ACTIVE'", (app, key)
            ).fetchone()
            if row is None or not principal.matches(json.loads(row["readers"])):
                raise PermissionError("Document unavailable")
            return serialize(row)

    def search(self, app, query, principal, limit=20):
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        terms = query.casefold().split()
        matches = []
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE app=? AND state='ACTIVE' ORDER BY key", (app,)
            )
            for row in rows:
                if not principal.matches(json.loads(row["readers"])):
                    continue
                text = row["text"].casefold()
                if all(term in text for term in terms):
                    matches.append(
                        serialize(row) | {"score": sum(text.count(term) for term in terms)}
                    )
        return sorted(matches, key=lambda item: (-item["score"], item["key"]))[:limit]

    def describe(self, app, principal):
        with self.database.connection() as connection:
            visible = sum(
                principal.matches(json.loads(row["readers"]))
                for row in connection.execute(
                    "SELECT readers FROM documents WHERE app=? AND state='ACTIVE'", (app,)
                )
            )
        return {
            "method": "lexical",
            "query": "all whitespace-separated terms, case insensitive",
            "score": "sum of matching term occurrences",
            "limit": {"default": 20, "maximum": 1000},
            "visible_documents": visible,
        }
