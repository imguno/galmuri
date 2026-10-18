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
    namespace,
    snapshot,
)
from galmuri.retrieval.validation import vector


class Search:
    def __init__(self, database, apps):
        self.database, self.apps = database, apps

    def visible(self, app_name, principal):
        app = self.apps[app_name]
        with self.database.connection() as connection:
            if not compatible(connection, app):
                raise ValueError("Retrieval configuration is no longer active; reload the runtime")
            return {
                row["key"]: dict(row)
                for row in current_documents(connection, app_name)
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

    def search(self, app_name, query, principal, limit=20, mode=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not isinstance(query, str):
            raise TypeError("query must be text")
        config = self.apps[app_name].retrieval
        selected = mode or config.mode
        if selected not in {"lexical", "vector", "hybrid"}:
            raise ValueError("mode must be lexical, vector or hybrid")
        documents = self.visible(app_name, principal)
        if not documents:
            return []
        candidate_limit = min(1000, max(64, limit * 4)) if selected == "hybrid" else limit
        lexical = self.lexical(documents, query) if selected in {"lexical", "hybrid"} else []
        semantic = (
            self.semantic(app_name, query, principal, candidate_limit)[:candidate_limit]
            if selected in {"vector", "hybrid"}
            else []
        )
        # Revalidate lexical candidates after possible embedding/store IO.
        current = self.visible(app_name, principal)
        if semantic:
            manifests = self.manifests(app_name, current)
            semantic = [
                item
                for item in semantic
                if item["key"] in manifests and manifests[item["key"]]["id"] == item["build"]
            ]
        if selected == "vector":
            return semantic[:limit]
        lexical = [
            item
            for item in lexical
            if item["key"] in current
            and snapshot(current[item["key"]])[0] == snapshot(documents[item["key"]])[0]
        ]
        if selected == "lexical":
            return lexical[:limit]
        fused = {}
        scores = {}
        for ranking in (lexical[:candidate_limit], semantic):
            for rank, item in enumerate(ranking, 1):
                key = item["key"]
                fused[key] = fused.get(key, {}) | item
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        return sorted(
            (item | {"score": scores[key], "search_mode": "hybrid"} for key, item in fused.items()),
            key=lambda item: (-item["score"], item["key"]),
        )[:limit]

    @staticmethod
    def lexical(documents, query):
        terms = query.casefold().split()
        found = []
        for document in documents.values():
            text = document["text"].casefold()
            if all(term in text for term in terms):
                found.append(
                    serialize(document)
                    | {"score": sum(text.count(term) for term in terms), "search_mode": "lexical"}
                )
        return sorted(found, key=lambda item: (-item["score"], item["key"]))

    def semantic(self, app_name, query, principal, limit):
        config = self.apps[app_name].retrieval
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
