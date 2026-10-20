"""One-time upgrade, serialized with the same lock as document publication."""

from galmuri.documents.lexical.analyzer import VERSION, analyze
from galmuri.documents.lexical.projection import replace


def initialize(database):
    # Existing databases need a one-time scan under the metadata writer lock.
    # Only the built-in Unicode analyzer runs here, never callbacks or external
    # IO. A failed upgrade rolls back postings and its version marker.
    with database.transaction() as connection:
        existing = connection.execute(
            "SELECT value FROM lexical_metadata WHERE name='analyzer'"
        ).fetchone()
        if existing:
            if existing["value"] != VERSION:
                raise ValueError("Lexical index analyzer is incompatible with this runtime")
            return
        rows = connection.execute(
            "SELECT d.app,d.key,d.text FROM documents d "
            "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
            "JOIN app_state a ON a.name=d.app "
            "WHERE d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version"
        )
        for row in rows:
            replace(connection, row["app"], row["key"], analyze(row["text"]))
        connection.execute(
            "INSERT INTO lexical_metadata(name,value) VALUES('analyzer',?)", (VERSION,)
        )
