"""App-selected query policy, independent of embedding artifact identity."""

from collections.abc import Callable
from dataclasses import dataclass, field

from galmuri.retrieval.search.fusion import ReciprocalRankFusion


@dataclass(frozen=True)
class SearchConfig:
    # lexical(query, *, app, limit) -> ordered iterable[SearchCandidate].
    # None selects the transactionally maintained built-in BM25 index.
    lexical: Callable | None = None
    # fusion(read-only mapping[str, tuple[SearchCandidate]]) -> ordered candidates.
    fusion: Callable = field(default_factory=ReciprocalRankFusion)
    candidate_limit: int = 1000

    def __post_init__(self):
        if self.lexical is not None and not callable(self.lexical):
            raise TypeError("lexical must be callable")
        if not callable(self.fusion):
            raise TypeError("fusion must be callable")
        if type(self.candidate_limit) is not int or not 1 <= self.candidate_limit <= 1000:
            raise ValueError("candidate_limit must be between 1 and 1000")

    def describe(self):
        def name(process):
            # Names are descriptive, not vector artifact invalidation keys.
            from galmuri.contracts.callables import callable_location

            return getattr(process, "identity", None) or callable_location(process)

        return {
            "lexical": name(self.lexical) if self.lexical is not None else "builtin-bm25",
            "fusion": name(self.fusion),
            "candidate_limit": self.candidate_limit,
            "candidate_window": "min(candidate_limit, max(64, 4 * requested_limit)) for hybrid",
        }
