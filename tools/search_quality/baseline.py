"""Former Queries.search algorithm, preserved for comparison on the same DB.

Source: src/galmuri/documents/queries.py at Git commit
bc3c2b52f589354f3dc403b7fa771be0bbc3fc2c, before indexed lexical search.
The SQL scan, ACL test, all-term substring check, occurrence score and tie-break
match that implementation. This is an evaluation baseline, never a runtime path.
"""

import json


def substring_search(database, app, query, principal, limit=20):
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    terms = query.casefold().split()
    matches = []
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM documents WHERE app=? AND state='ACTIVE' ORDER BY key", (app,)
        )
        for row in rows:
            if not principal.matches(json.loads(row["readers"])):
                continue
            text = row["text"].casefold()
            if all(term in text for term in terms):
                matches.append(
                    {
                        "key": row["key"],
                        "text": row["text"],
                        "metadata": json.loads(row["metadata"]),
                        "version": row["version"],
                        "source_key": row["source_key"],
                        "score": sum(text.count(term) for term in terms),
                    }
                )
    return sorted(matches, key=lambda item: (-item["score"], item["key"]))[:limit]
