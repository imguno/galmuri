"""Embedding and materialized vector retrieval contracts."""

from galmuri.retrieval.chunking import CharacterChunker, ChunkingConfig
from galmuri.retrieval.config import RetrievalConfig
from galmuri.retrieval.embeddings import EmbeddingConfig, FastEmbedEmbedding, OpenAIEmbedding
from galmuri.retrieval.errors import ProviderError, RetrievalError, VectorValidationError
from galmuri.retrieval.models import Chunk, EmbeddingSpec, VectorMatch, VectorPoint
from galmuri.retrieval.ports import Chunker, EmbeddingProvider, VectorStore
from galmuri.retrieval.stores import PostgresVectorStore, QdrantVectorStore, SQLiteVectorStore

__all__ = [
    "CharacterChunker",
    "Chunk",
    "Chunker",
    "ChunkingConfig",
    "EmbeddingConfig",
    "EmbeddingProvider",
    "EmbeddingSpec",
    "ProviderError",
    "RetrievalConfig",
    "RetrievalError",
    "VectorMatch",
    "VectorPoint",
    "VectorStore",
    "VectorValidationError",
    "FastEmbedEmbedding",
    "OpenAIEmbedding",
    "QdrantVectorStore",
    "PostgresVectorStore",
    "SQLiteVectorStore",
]
