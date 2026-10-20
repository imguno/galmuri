"""Authorization fences bracket external IO; remote payload never grants access."""

import json
import math
from dataclasses import asdict
from itertools import islice

from galmuri.documents.queries import serialize
from galmuri.retrieval.errors import ProviderError, RetrievalError
from galmuri.retrieval.indexing.snapshots import (
    compatible,
    current_documents,
    has_visible_vectors,
    namespace,
    snapshot,
)
from galmuri.retrieval.validation import vector


class SemanticSearch:
    def __init__(self, database, apps):
        self.database, self.apps = database, apps

    def visible(self, app_name, principal, keys=None):
        app = self.apps[app_name]
        with self.database.connection() as connection:
            if not compatible(connection, app):
                raise ValueError("Retrieval configuration is no longer active; reload the runtime")
            return {
                row["key"]: dict(row)
                for row in current_documents(connection, app_name, keys=keys)
                if principal.matches(json.loads(row["readers"]))
            }

    def manifests(self, app_name, documents):
        app = self.apps[app_name]
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT b.* FROM semantic_heads h JOIN semantic_builds b ON b.id=h.build "
                "WHERE h.app=? AND b.state='PUBLISHED' AND b.fingerprint=? AND b.revision=?",
                (app_name, app.retrieval.fingerprint, app.revision),
            ).fetchall()
        return {
            row["key"]: dict(row)
            for row in rows
            if row["key"] in documents and row["snapshot"] == snapshot(documents[row["key"]])[0]
        }

    def semantic(self, app_name, query, principal, limit):
        app = self.apps[app_name]
        config = app.retrieval
        with self.database.connection() as connection:
            if not has_visible_vectors(connection, app, principal):
                return []
        query_vector = vector(config.embedding.embed_query(query), config.embedding.spec.dimensions)
        config.store.ensure(namespace(config.fingerprint), config.embedding.spec.dimensions)
        # The allow-list is acquired after embedding, immediately before nearest-neighbor IO.
        documents = self.visible(app_name, principal)
        manifests = self.manifests(app_name, documents)
        points = {}
        for key, job in manifests.items():
            for chunk in json.loads(job["prepared"]):
                points[chunk["id"]] = (key, job, chunk)
        if not points:
            return []
        matches = self.neighbors(app_name, query_vector, points, limit, principal)
        # Fetch current grants, intent, configuration and active build again after external IO.
        current = self.visible(app_name, principal)
        active = self.manifests(app_name, current)
        results = {}
        for match in matches:
            if match.id not in points:
                continue
            key, job, chunk = points[match.id]
            if key not in active or active[key]["id"] != job["id"]:
                continue
            anchor = {name: chunk[name] for name in ("id", "text", "start", "end")}
            if key not in results:
                results[key] = serialize(current[key]) | {
                    "score": match.score,
                    "search_mode": "vector",
                    "chunks": [],
                    "build": job["id"],
                    "fingerprint": config.fingerprint,
                    "embedding": asdict(config.embedding.spec),
                }
            results[key]["score"] = max(results[key]["score"], match.score)
            results[key]["chunks"].append(anchor | {"score": match.score})
        return sorted(results.values(), key=lambda item: (-item["score"], item["key"]))

    def neighbors(self, app_name, query_vector, points, limit, principal):
        """Grow a bounded chunk window until document top-k is determined."""
        config = self.apps[app_name].retrieval
        window = min(len(points), max(32, limit * 4), 10_000)
        while True:
            current = self.manifests(app_name, self.visible(app_name, principal))
            allowed = tuple(
                identifier
                for identifier, (key, job, _) in points.items()
                if key in current and current[key]["id"] == job["id"]
            )
            if not allowed:
                return ()
            matches = tuple(
                islice(
                    iter(
                        config.store.search(
                            namespace(config.fingerprint),
                            query_vector,
                            allowed_ids=allowed,
                            limit=window,
                        )
                    ),
                    window + 1,
                )
            )
            if len(matches) > window:
                raise ProviderError("Vector store exceeded the requested result count")
            identifiers = set()
            previous = float("inf")
            by_document = {}
            for match in matches:
                if (
                    match.id not in allowed
                    or match.id in identifiers
                    or not math.isfinite(match.score)
                    or match.score > previous
                ):
                    raise ProviderError("Vector store returned invalid or unordered matches")
                identifiers.add(match.id)
                previous = match.score
                key = points[match.id][0]
                by_document[key] = max(match.score, by_document.get(key, float("-inf")))
            scores = sorted(by_document.values(), reverse=True)
            exhausted = len(matches) < window or len(matches) >= len(allowed)
            determined = len(scores) >= limit and matches[-1].score < scores[limit - 1]
            if exhausted or determined:
                return matches
            if window >= 10_000:
                raise RetrievalError(
                    "Document top-k exceeds the 10000-chunk query budget; "
                    "reduce the limit or use larger chunks"
                )
            window = min(len(allowed), window * 2, 10_000)
