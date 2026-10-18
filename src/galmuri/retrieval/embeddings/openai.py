"""OpenAI embeddings API with configurable model, dimensions and endpoint."""

import hashlib

from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.http import JSONClient
from galmuri.retrieval.models import EmbeddingSpec
from galmuri.retrieval.ports import EmbeddingProvider
from galmuri.retrieval.validation import label, vector


class OpenAIEmbedding(EmbeddingProvider):
    def __init__(
        self,
        api_key: str,
        model="text-embedding-3-small",
        dimensions=1536,
        revision="1",
        base_url="https://api.openai.com/v1",
        timeout=30,
    ):
        label(api_key, "api_key")
        self._http = JSONClient(base_url, {"Authorization": f"Bearer {api_key}"}, timeout)
        # Compatible endpoints may serve different weights under the same model name.
        provider = "openai"
        if self._http.url != "https://api.openai.com/v1":
            provider += ":" + hashlib.sha256(self._http.url.encode()).hexdigest()[:16]
        self._spec = EmbeddingSpec(provider, model, dimensions, revision)

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        result = self._http.request(
            "POST",
            "/embeddings",
            {
                "model": self.spec.model,
                "dimensions": self.spec.dimensions,
                "input": list(texts),
                "encoding_format": "float",
            },
        )
        data = result.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise ProviderError("embedding provider returned the wrong number of vectors")
        ordered = {}
        for item in data:
            if not isinstance(item, dict) or type(item.get("index")) is not int:
                raise ProviderError("embedding response has an invalid index")
            index = item["index"]
            if index < 0 or index >= len(texts) or index in ordered:
                raise ProviderError("embedding response has duplicate or invalid indices")
            ordered[index] = vector(item.get("embedding"), self.spec.dimensions)
        return tuple(ordered[index] for index in range(len(texts)))

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self.embed_documents((text,))[0]
