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
    def __init__(self, database, apps=None):
        self.database = database
        self.apps = apps

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
        from galmuri.documents.lexical import LexicalIndex

        revision = self.apps[app].revision if self.apps is not None else None
        return LexicalIndex(self.database, revision=revision).search(app, query, principal, limit)

    def describe(self, app, principal):
        from galmuri.documents.lexical import LexicalIndex

        with self.database.connection() as connection:
            visible = sum(
                principal.matches(json.loads(row["readers"]))
                for row in connection.execute(
                    "SELECT d.readers FROM documents d "
                    "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
                    "WHERE d.app=? AND d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version",
                    (app,),
                )
            )
        return LexicalIndex.describe() | {"visible_documents": visible}
