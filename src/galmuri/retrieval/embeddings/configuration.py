"""Pair explicit document and query callables under one embedding-space contract."""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from itertools import islice

from galmuri.contracts.callables import callable_identity, callable_location
from galmuri.retrieval.errors import VectorValidationError
from galmuri.retrieval.models import EmbeddingSpec
from galmuri.retrieval.ports import EmbeddingProvider
from galmuri.retrieval.validation import label, vector


def _binding(process, identity, name):
    selected = callable_identity(process, identity, name=name)
    return [selected, callable_location(process)]


@dataclass(frozen=True, init=False)
class EmbeddingConfig(EmbeddingProvider):
    process: Callable[[tuple[str, ...]], Iterable[Iterable[float]]]
    query_process: Callable[[str], Iterable[float]]
    declared_spec: EmbeddingSpec
    identity: str | None
    revision: str
    _spec: EmbeddingSpec

    def __init__(self, process, query_process, spec, *, identity=None, revision="1"):
        if not isinstance(spec, EmbeddingSpec):
            raise TypeError("Embedding configuration requires an EmbeddingSpec")
        label(revision, "embedding revision")
        documents = _binding(process, identity, "document embedding process")
        query = _binding(query_process, identity, "query embedding process")
        value = {"documents": documents, "query": query, "revision": revision, "spec": asdict(spec)}
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        for name, item in (
            ("process", process),
            ("query_process", query_process),
            ("declared_spec", spec),
            ("identity", identity),
            ("revision", revision),
            ("_spec", replace(spec, revision=f"{spec.revision}:binding:{digest}")),
        ):
            object.__setattr__(self, name, item)

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not isinstance(texts, tuple) or not all(isinstance(text, str) for text in texts):
            raise TypeError("Document embedding input must be a tuple of strings")
        if not texts:
            return ()
        values = self.process(texts)
        try:
            iterator = iter(values)
        except TypeError as error:
            raise VectorValidationError("Embedding process must return a vector batch") from error
        batch = tuple(islice(iterator, len(texts) + 1))
        if len(batch) != len(texts):
            raise VectorValidationError("Embedding process returned an incorrect batch length")
        return tuple(vector(item, self.spec.dimensions) for item in batch)

    def embed_query(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str):
            raise TypeError("Query embedding input must be text")
        return vector(self.query_process(text), self.spec.dimensions)

    @classmethod
    def from_provider(cls, provider: EmbeddingProvider, *, revision="1"):
        """Bind a configured provider; its declared spec identifies model options."""
        spec = getattr(provider, "spec", None)
        if not isinstance(spec, EmbeddingSpec):
            raise TypeError("Embedding provider requires an EmbeddingSpec")
        return cls(
            provider.embed_documents,
            provider.embed_query,
            spec,
            identity=callable_location(type(provider)),
            revision=revision,
        )
