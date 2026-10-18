"""Durable exact cosine reference store for small deployments (no ANN index)."""

import json
import math
from pathlib import Path

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.models import VectorMatch, VectorPoint
from galmuri.retrieval.ports import VectorStore
from galmuri.retrieval.stores.cosine import unit
from galmuri.retrieval.validation import label, point_id, positive_int
from galmuri.retrieval.validation import vector as validate_vector
from galmuri.storage.database import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vector_spaces (
    namespace TEXT PRIMARY KEY, dimensions INTEGER NOT NULL CHECK(dimensions > 0)
);
CREATE TABLE IF NOT EXISTS vector_points (
    namespace TEXT NOT NULL REFERENCES vector_spaces(namespace),
    id TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(namespace,id)
);
"""


class SQLiteVectorStore(VectorStore):
    def __init__(self, path: str | Path):
        self._database = Database(path)
        self._database.initialize(_SCHEMA)

    @property
    def identity(self) -> str:
        return "sqlite-cosine:v1:" + self._database.path.as_posix()

    def ensure(self, namespace: str, dimensions: int) -> None:
        label(namespace, "namespace")
        positive_int(dimensions, "dimensions")
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO vector_spaces VALUES (?,?)", (namespace, dimensions)
            )
            if self._dimensions(connection, namespace) != dimensions:
                raise ProviderError("vector namespace has incompatible dimensions")

    @staticmethod
    def _dimensions(connection, namespace):
        row = connection.execute(
            "SELECT dimensions FROM vector_spaces WHERE namespace=?", (namespace,)
        ).fetchone()
        if row is None:
            raise ProviderError("vector namespace has not been ensured")
        return row["dimensions"]

    def upsert(self, namespace: str, points: tuple[VectorPoint, ...]) -> None:
        with self._database.transaction() as connection:
            dimensions = self._dimensions(connection, namespace)
            rows = [
                (
                    namespace,
                    point_id(point.id),
                    json.dumps(unit(validate_vector(point.vector, dimensions)), allow_nan=False),
                )
                for point in points
            ]
            connection.executemany(
                "INSERT INTO vector_points VALUES (?,?,?) "
                "ON CONFLICT(namespace,id) DO UPDATE SET vector=excluded.vector",
                rows,
            )

    def search(
        self, namespace: str, vector: tuple[float, ...], *, allowed_ids: tuple[str, ...], limit: int
    ) -> tuple[VectorMatch, ...]:
        positive_int(limit, "limit")
        ids = tuple(dict.fromkeys(point_id(value) for value in allowed_ids))
        if not ids:
            return ()
        with self._database.connection() as connection:
            dimensions = self._dimensions(connection, namespace)
            query = unit(validate_vector(vector, dimensions))
            matches = []
            # Bound SQLite parameter count. Authorization restricts rows before scoring/top-k.
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    f"SELECT id,vector FROM vector_points WHERE namespace=? "
                    f"AND id IN ({placeholders})",
                    (namespace, *batch),
                )
                for row in rows:
                    score = math.fsum(
                        a * b for a, b in zip(query, json.loads(row["vector"]), strict=True)
                    )
                    matches.append(VectorMatch(row["id"], max(-1.0, min(1.0, score))))
        return tuple(sorted(matches, key=lambda match: (-match.score, match.id))[:limit])

    def delete(self, namespace: str, ids: tuple[str, ...]) -> None:
        rows = [(namespace, point_id(value)) for value in ids]
        with self._database.transaction() as connection:
            connection.executemany("DELETE FROM vector_points WHERE namespace=? AND id=?", rows)
