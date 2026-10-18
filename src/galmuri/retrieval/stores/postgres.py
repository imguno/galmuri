"""Remote exact cosine reference store, without an ANN extension requirement."""

import json
import math

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.models import VectorMatch, VectorPoint
from galmuri.retrieval.ports import VectorStore
from galmuri.retrieval.stores.cosine import unit
from galmuri.retrieval.validation import label, point_id, positive_int
from galmuri.retrieval.validation import vector as validate_vector
from galmuri.storage.postgres import PostgresDatabase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vector_spaces (
    namespace TEXT PRIMARY KEY, dimensions INTEGER NOT NULL CHECK(dimensions > 0)
);
CREATE TABLE IF NOT EXISTS vector_points (
    namespace TEXT NOT NULL REFERENCES vector_spaces(namespace),
    id TEXT NOT NULL, vector TEXT NOT NULL, PRIMARY KEY(namespace,id)
);
"""


class PostgresVectorStore(VectorStore):
    def __init__(self, dsn: str | None = None, *, schema="public", database=None):
        if database is not None and dsn is not None:
            raise ValueError("Specify either dsn or database")
        self._database = database if database is not None else PostgresDatabase(dsn, schema=schema)

    @property
    def identity(self) -> str:
        return "postgres-cosine:v1:" + self._database.identity

    def ensure(self, namespace: str, dimensions: int) -> None:
        label(namespace, "namespace")
        positive_int(dimensions, "dimensions")
        self._database.initialize(_SCHEMA)
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO vector_spaces VALUES (?,?) ON CONFLICT DO NOTHING",
                (namespace, dimensions),
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

    def search(self, namespace, vector, *, allowed_ids, limit) -> tuple[VectorMatch, ...]:
        positive_int(limit, "limit")
        ids = tuple(dict.fromkeys(point_id(value) for value in allowed_ids))
        if not ids:
            return ()
        with self._database.connection() as connection:
            dimensions = self._dimensions(connection, namespace)
            query = unit(validate_vector(vector, dimensions))
            matches = []
            # Bound statement size; authorization filters candidates before top-k.
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                marks = ",".join("?" for _ in batch)
                rows = connection.execute(
                    f"SELECT id,vector FROM vector_points WHERE namespace=? AND id IN ({marks})",
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
