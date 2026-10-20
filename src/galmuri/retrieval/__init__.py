"""Embedding and materialized vector retrieval contracts."""

from galmuri.retrieval.chunking import (
    CharacterChunker,
    ChunkingConfig,
    StructureChunker,
    TokenBudgetChunker,
)
from galmuri.retrieval.config import RetrievalConfig
from galmuri.retrieval.embeddings import EmbeddingConfig, FastEmbedEmbedding, OpenAIEmbedding
from galmuri.retrieval.errors import ProviderError, RetrievalError, VectorValidationError
from galmuri.retrieval.models import Chunk, EmbeddingSpec, VectorMatch, VectorPoint
from galmuri.retrieval.ports import Chunker, EmbeddingProvider, VectorStore
from galmuri.retrieval.search.configuration import SearchConfig
from galmuri.retrieval.search.contracts import SearchCandidate
from galmuri.retrieval.search.fusion import ReciprocalRankFusion
from galmuri.retrieval.stores import PostgresVectorStore, QdrantVectorStore, SQLiteVectorStore

__all__ = [
    "SearchConfig",
    "SearchCandidate",
    "ReciprocalRankFusion",
    "CharacterChunker",
    "Chunk",
    "Chunker",
    "ChunkingConfig",
    "StructureChunker",
    "TokenBudgetChunker",
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
