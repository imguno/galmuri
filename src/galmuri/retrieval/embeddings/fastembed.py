"""Local ONNX embeddings using FastEmbed's model-specific passage/query paths."""

import hashlib
import json
from itertools import islice
from threading import Lock

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.models import EmbeddingSpec
from galmuri.retrieval.ports import EmbeddingProvider
from galmuri.retrieval.validation import label, positive_int, vector


class FastEmbedEmbedding(EmbeddingProvider):
    def __init__(
        self,
        model="BAAI/bge-small-en-v1.5",
        cache_dir=None,
        revision="1",
        *,
        threads: int = 2,
        passage_prefix: str = "",
        query_prefix: str = "",
    ):
        label(model, "model")
        label(revision, "revision")
        positive_int(threads, "threads")
        if not isinstance(passage_prefix, str) or not isinstance(query_prefix, str):
            raise TypeError("Embedding prefixes must be text")
        self.model = model
        self.cache_dir = None if cache_dir is None else str(cache_dir)
        self.revision = revision
        self.threads = threads
        self.passage_prefix, self.query_prefix = passage_prefix, query_prefix
        self._model = None
        self._budget = None
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
        revision = self.revision
        if self.passage_prefix or self.query_prefix:
            encoded = json.dumps([self.passage_prefix, self.query_prefix])
            revision += ":prefixes:" + hashlib.sha256(encoded.encode()).hexdigest()
        return EmbeddingSpec(
            "fastembed", self.model, implementation.get_embedding_size(self.model), revision
        )

    def default_chunker(self, base):
        """Default chunks fit the actual model input; configuration stays lazy."""
        from galmuri.retrieval.embeddings.tokenization import ModelChunker

        return ModelChunker(self, base)

    def _token_budget(self):
        from galmuri.retrieval.embeddings.tokenization import token_budget

        model = self._load()
        with self._lock:
            if self._budget is None:
                self._budget = token_budget(model)
            return self._budget

    def _check_input(self, texts):
        tokenizer, limit = self._token_budget()
        if any(len(tokenizer.encode(text).ids) > limit for text in texts):
            raise ProviderError(
                f"Embedding input exceeds the model's {limit}-token budget; "
                "use the default token-aware chunker or shorter queries"
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
        prepared = tuple(self.passage_prefix + text for text in texts)
        self._check_input(prepared)
        values = islice(self._load().passage_embed(prepared), len(texts) + 1)
        result = tuple(vector(value, dimensions) for value in values)
        if len(result) != len(texts):
            raise ProviderError("embedding provider returned the wrong number of vectors")
        return result

    def embed_query(self, text: str) -> tuple[float, ...]:
        prepared = self.query_prefix + text
        self._check_input((prepared,))
        result = tuple(islice(self._load().query_embed(prepared), 2))
        if len(result) != 1:
            raise ProviderError("embedding provider returned the wrong number of query vectors")
        return vector(result[0], self.spec.dimensions)
