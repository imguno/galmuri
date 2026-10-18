"""SQLite is the local multi-process coordinator backend."""

from pathlib import Path

from galmuri.execution.persistence.composition import open_relational
from galmuri.storage.database import Database


class SQLiteBackend:
    def __init__(self, path, *, vector_path=None):
        self.path = Path(path).resolve()
        self.identity = "sqlite:" + self.path.as_posix()
        self.vector_path = (
            Path(vector_path).resolve() if vector_path else self.path.parent / "vectors.sqlite3"
        )

    def default_store(self, app=None):
        from galmuri.retrieval.stores.sqlite import SQLiteVectorStore

        return SQLiteVectorStore(self.vector_path)

    def open(self, apps, clock, *, activate=False):
        return open_relational(Database(self.path), apps, clock, activate=activate)
