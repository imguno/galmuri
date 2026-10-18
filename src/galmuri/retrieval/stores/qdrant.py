"""Qdrant REST storage; authorized UUIDs are filtered inside nearest-neighbor queries."""

import hashlib
import math
import re

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.http import JSONClient, ProviderHTTPError
from galmuri.retrieval.models import VectorMatch, VectorPoint
from galmuri.retrieval.ports import VectorStore
from galmuri.retrieval.validation import label, point_id, positive_int
from galmuri.retrieval.validation import vector as validate_vector


class QdrantVectorStore(VectorStore):
    def __init__(self, url: str, api_key=None, prefix="framework", timeout=30):
        if not isinstance(prefix, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", prefix):
            raise ValueError("collection prefix must contain 1-64 letters, digits, _ or -")
        headers = {} if api_key is None else {"api-key": api_key}
        self._http = JSONClient(url, headers, timeout)
        self.prefix = prefix
        self._dimensions: dict[str, int] = {}

    @property
    def identity(self) -> str:
        return f"qdrant-cosine:v1:{self._http.url}:{self.prefix}"

    def _collection(self, namespace):
        label(namespace, "namespace")
        digest = hashlib.sha256(namespace.encode()).hexdigest()
        return f"/collections/{self.prefix}_{digest}"

    def ensure(self, namespace: str, dimensions: int) -> None:
        positive_int(dimensions, "dimensions")
        path = self._collection(namespace)
        try:
            result = self._http.request("GET", path)
        except ProviderHTTPError as exc:
            if exc.status != 404:
                raise
            try:
                self._http.request(
                    "PUT", path, {"vectors": {"size": dimensions, "distance": "Cosine"}}
                )
            except ProviderHTTPError as creation_error:
                if creation_error.status not in {400, 409}:
                    raise
                # Another process may have created the collection: always verify it below.
            result = self._http.request("GET", path)
        try:
            vectors = result["result"]["config"]["params"]["vectors"]
            if (
                type(vectors["size"]) is not int
                or vectors["size"] != dimensions
                or vectors["distance"].lower() != "cosine"
            ):
                raise ProviderError("Qdrant collection has incompatible dimensions or metric")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProviderError(
                "Qdrant collection has an unsupported vector configuration"
            ) from exc
        self._dimensions[namespace] = dimensions

    def _dimension(self, namespace):
        if namespace not in self._dimensions:
            raise ProviderError("vector namespace has not been ensured")
        return self._dimensions[namespace]

    def upsert(self, namespace: str, points: tuple[VectorPoint, ...]) -> None:
        dimensions = self._dimension(namespace)
        values = [
            {"id": point_id(point.id), "vector": list(validate_vector(point.vector, dimensions))}
            for point in points
        ]
        if values:
            self._http.request(
                "PUT", self._collection(namespace) + "/points?wait=true", {"points": values}
            )

    def search(
        self, namespace: str, vector: tuple[float, ...], *, allowed_ids: tuple[str, ...], limit: int
    ) -> tuple[VectorMatch, ...]:
        positive_int(limit, "limit")
        ids = tuple(dict.fromkeys(point_id(value) for value in allowed_ids))
        if not ids:
            return ()
        query = validate_vector(vector, self._dimension(namespace))
        result = self._http.request(
            "POST",
            self._collection(namespace) + "/points/query",
            {
                "query": list(query),
                "filter": {"must": [{"has_id": list(ids)}]},
                "limit": limit,
                "with_payload": False,
                "with_vector": False,
            },
        )
        try:
            points = result["result"]["points"]
            if not isinstance(points, list) or len(points) > limit:
                raise ProviderError("Qdrant returned an invalid result count")
            allowed = set(ids)
            matches = []
            seen = set()
            for item in points:
                identifier, score = point_id(item["id"]), float(item["score"])
                if identifier not in allowed or identifier in seen or not math.isfinite(score):
                    raise ProviderError("Qdrant returned an invalid filtered match")
                seen.add(identifier)
                matches.append(VectorMatch(identifier, score))
            return tuple(matches)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ProviderError("Qdrant returned an invalid query result") from exc

    def delete(self, namespace: str, ids: tuple[str, ...]) -> None:
        values = list(dict.fromkeys(point_id(value) for value in ids))
        if values:
            self._http.request(
                "POST", self._collection(namespace) + "/points/delete?wait=true", {"points": values}
            )
