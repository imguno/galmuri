"""App-owned projection policy and deterministic generation identity."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

from galmuri.retrieval.chunking import CharacterChunker
from galmuri.retrieval.models import EmbeddingSpec
from galmuri.retrieval.ports import Chunker, EmbeddingProvider, VectorStore
from galmuri.retrieval.validation import label, positive_int


@dataclass(frozen=True)
class RetrievalConfig:
    embedding: EmbeddingProvider | None = None
    store: VectorStore | None = None
    chunker: Chunker = field(default_factory=CharacterChunker)
    mode: str | None = None
    revision: str = "1"
    batch_size: int = 32
    max_attempts: int = 3
    retry_delay: float = 1
    lease_seconds: float = 60
    cleanup_interval: float = 300

    def __post_init__(self):
        if self.mode is None and self.embedding is not None and self.store is not None:
            object.__setattr__(self, "mode", "vector")
        if self.mode is not None and (
            not isinstance(self.mode, str) or self.mode not in {"lexical", "vector", "hybrid"}
        ):
            raise ValueError("mode must be lexical, vector or hybrid")
        label(self.revision, "revision")
        if not callable(getattr(self.chunker, "split", None)):
            raise TypeError("Chunker must implement split")
        label(getattr(self.chunker, "identity", None), "chunker identity")
        if self.embedding is not None:
            if not isinstance(getattr(self.embedding, "spec", None), EmbeddingSpec) or not all(
                callable(getattr(self.embedding, name, None))
                for name in ("embed_documents", "embed_query")
            ):
                raise TypeError("Embedding must provide an EmbeddingSpec and embedding methods")
        if self.store is not None:
            if not all(
                callable(getattr(self.store, name, None))
                for name in ("ensure", "upsert", "search", "delete")
            ):
                raise TypeError("Store must implement ensure, upsert, search and delete")
            label(getattr(self.store, "identity", None), "store identity")
        positive_int(self.batch_size, "batch_size")
        positive_int(self.max_attempts, "max_attempts")
        for name in ("retry_delay", "lease_seconds", "cleanup_interval"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            if not math.isfinite(value) or value < 0 or (name != "retry_delay" and value == 0):
                raise ValueError(f"{name} must be finite and positive (retry delay may be zero)")

    @property
    def fingerprint(self) -> str:
        if self.embedding is None or self.store is None:
            raise ValueError(
                "Resolve retrieval defaults through an App before using its fingerprint"
            )
        value = {
            "embedding": asdict(self.embedding.spec),
            "chunker": self.chunker.identity,
            "store": self.store.identity,
            "revision": self.revision,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
