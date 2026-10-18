"""Local ONNX embeddings using FastEmbed's model-specific passage/query paths."""

from itertools import islice
from threading import Lock

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.models import EmbeddingSpec
from galmuri.retrieval.ports import EmbeddingProvider
from galmuri.retrieval.validation import label, positive_int, vector


class FastEmbedEmbedding(EmbeddingProvider):
    def __init__(
        self, model="BAAI/bge-small-en-v1.5", cache_dir=None, revision="1", *, threads: int = 2
    ):
        label(model, "model")
        label(revision, "revision")
        positive_int(threads, "threads")
        self.model = model
        self.cache_dir = None if cache_dir is None else str(cache_dir)
        self.revision = revision
        self.threads = threads
        self._model = None
        self._lock = Lock()

    @staticmethod
    def _implementation():
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ProviderError("install galmuri[embeddings] to use FastEmbed") from exc
        return TextEmbedding

    @property
    def spec(self) -> EmbeddingSpec:
        # Model registry lookup imports the optional package but does not download weights.
        implementation = self._implementation()
        return EmbeddingSpec(
            "fastembed", self.model, implementation.get_embedding_size(self.model), self.revision
        )

    def _load(self):
        with self._lock:
            if self._model is None:
                self._model = self._implementation()(
                    model_name=self.model,
                    cache_dir=self.cache_dir,
                    threads=self.threads,
                    providers=["CPUExecutionProvider"],
                )
            return self._model

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        dimensions = self.spec.dimensions
        values = islice(self._load().passage_embed(texts), len(texts) + 1)
        result = tuple(vector(value, dimensions) for value in values)
        if len(result) != len(texts):
            raise ProviderError("embedding provider returned the wrong number of vectors")
        return result

    def embed_query(self, text: str) -> tuple[float, ...]:
        result = tuple(islice(self._load().query_embed(text), 2))
        if len(result) != 1:
            raise ProviderError("embedding provider returned the wrong number of query vectors")
        return vector(result[0], self.spec.dimensions)
