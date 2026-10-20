"""Rank fusion without assuming comparable BM25 and cosine score scales."""

import json
import math
from dataclasses import dataclass

from galmuri.retrieval.search.contracts import SearchCandidate


@dataclass(frozen=True)
class ReciprocalRankFusion:
    """Weighted RRF. Zero weight disables a ranking's contribution."""

    k: float = 60
    lexical_weight: float = 1
    vector_weight: float = 1

    def __post_init__(self):
        for name in ("k", "lexical_weight", "vector_weight"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be finite and nonnegative")
        if not self.lexical_weight and not self.vector_weight:
            raise ValueError("At least one fusion weight must be positive")

    @property
    def identity(self):
        return "rrf:v1:" + json.dumps([self.k, self.lexical_weight, self.vector_weight])

    def __call__(self, rankings):
        scores = {}
        for name, weight in (("lexical", self.lexical_weight), ("vector", self.vector_weight)):
            if not weight:
                continue
            for rank, candidate in enumerate(rankings.get(name, ()), 1):
                scores[candidate.key] = scores.get(candidate.key, 0) + weight / (self.k + rank)
        return tuple(
            SearchCandidate(key, score)
            for key, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        )
