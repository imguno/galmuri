"""Provider-owned contracts without scheduling or authorization policy."""

from abc import ABC, abstractmethod

from galmuri.retrieval.models import Chunk, EmbeddingSpec, VectorMatch, VectorPoint


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def spec(self) -> EmbeddingSpec: ...

    @abstractmethod
    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...

    @abstractmethod
    def embed_query(self, text: str) -> tuple[float, ...]: ...


class Chunker(ABC):
    @property
    @abstractmethod
    def identity(self) -> str: ...

    @abstractmethod
    def split(self, text: str) -> tuple[Chunk, ...]: ...


class VectorStore(ABC):
    @property
    @abstractmethod
    def identity(self) -> str: ...

    @abstractmethod
    def ensure(self, namespace: str, dimensions: int) -> None: ...

    @abstractmethod
    def upsert(self, namespace: str, points: tuple[VectorPoint, ...]) -> None: ...

    @abstractmethod
    def search(
        self, namespace: str, vector: tuple[float, ...], *, allowed_ids: tuple[str, ...], limit: int
    ) -> tuple[VectorMatch, ...]: ...

    @abstractmethod
    def delete(self, namespace: str, ids: tuple[str, ...]) -> None: ...
