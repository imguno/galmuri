"""Search extensions exchange identities and scores, never authoritative documents."""

import math
from dataclasses import dataclass
from itertools import islice

from galmuri.retrieval.errors import ProviderError


@dataclass(frozen=True)
class SearchCandidate:
    key: str
    score: float

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("Search candidate key must be nonempty text")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise ValueError("Search candidate score must be finite")


def candidates(values, limit, *, allowed=None):
    """Bound lazy producers as well as materialized results; reject invalid rankings."""
    result = tuple(islice(iter(values), limit + 1))
    if len(result) > limit:
        raise ProviderError("Search extension exceeded its candidate limit")
    seen = set()
    previous = float("inf")
    for item in result:
        if not isinstance(item, SearchCandidate):
            raise ProviderError("Search extension returned an invalid candidate")
        try:
            SearchCandidate(item.key, item.score)
        except (TypeError, ValueError) as error:
            raise ProviderError("Search extension returned an invalid candidate") from error
        if (
            item.key in seen
            or item.score > previous
            or (allowed is not None and item.key not in allowed)
        ):
            raise ProviderError("Search extension returned invalid or unordered candidates")
        seen.add(item.key)
        previous = item.score
    return result
