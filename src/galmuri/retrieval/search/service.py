"""Bound query extensions; authoritative publication and ACL checks own every result."""

from types import MappingProxyType

from galmuri.documents.queries import Queries, serialize
from galmuri.retrieval.indexing.snapshots import snapshot
from galmuri.retrieval.search.contracts import SearchCandidate, candidates
from galmuri.retrieval.search.semantic import SemanticSearch


class Search(SemanticSearch):
    def search(self, app_name, query, principal, limit=20, mode=None):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not isinstance(query, str):
            raise TypeError("query must be text")
        if not query.strip():
            return []
        config = self.apps[app_name].retrieval
        selected = mode or config.mode
        if selected not in {"lexical", "vector", "hybrid"}:
            raise ValueError("mode must be lexical, vector or hybrid")
        policy = config.search
        # Query-policy changes do not invalidate vector artifacts.
        window = (
            min(policy.candidate_limit, max(64, limit * 4))
            if selected == "hybrid"
            else min(policy.candidate_limit, limit)
        )
        self.visible(app_name, principal, keys=())
        lexical = self.lexical(app_name, query, principal, window) if selected != "vector" else []
        semantic = (
            self.semantic(app_name, query, principal, window)[:window]
            if selected != "lexical"
            else []
        )
        current = self.visible(
            app_name, principal, keys=(item["key"] for item in (*lexical, *semantic))
        )
        payloads = {}
        manifests = self.manifests(app_name, current) if semantic else {}
        baseline = {}
        rankings = {}
        for name, items in (("lexical", lexical), ("vector", semantic)):
            accepted = []
            for item in items:
                key = item["key"]
                row = current.get(key)
                if row is None:
                    continue
                stored = serialize(row)
                if any(stored[field] != item[field] for field in stored):
                    continue
                if name == "vector" and (
                    key not in manifests or manifests[key]["id"] != item["build"]
                ):
                    continue
                baseline[key] = snapshot(row)[0]
                payloads[key] = item
                accepted.append(SearchCandidate(key, item["score"]))
            rankings[name] = tuple(accepted)
        if selected == "hybrid":
            ranked = candidates(
                policy.fusion(MappingProxyType(rankings)),
                len(baseline),
                allowed=baseline,
            )
        else:
            ranked = rankings[selected]
        # Fusion, lexical callbacks and lazy generators are user code / IO.
        # Recheck AFTER consumption; neither a score nor a returned ID grants access.
        current = self.visible(app_name, principal, keys=(item.key for item in ranked))
        manifests = self.manifests(app_name, current) if semantic else {}
        result = []
        for candidate in ranked:
            key = candidate.key
            row = current.get(key)
            if row is None or snapshot(row)[0] != baseline[key]:
                continue
            item = payloads[key]
            if "build" in item and (key not in manifests or manifests[key]["id"] != item["build"]):
                continue
            result.append(
                item | serialize(row) | {"score": candidate.score, "search_mode": selected}
            )
            if len(result) == limit:
                break
        return result

    def lexical(self, app_name, query, principal, limit):
        process = self.apps[app_name].retrieval.search.lexical
        if process is None:
            return Queries(self.database).search(app_name, query, principal, limit)
        ranked = candidates(process(query, app=app_name, limit=limit), limit)
        current = self.visible(app_name, principal, keys=(item.key for item in ranked))
        return [
            serialize(current[item.key]) | {"score": item.score, "search_mode": "lexical"}
            for item in ranked
            if item.key in current
        ]
