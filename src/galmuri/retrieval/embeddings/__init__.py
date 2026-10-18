"""Optional actual neural embedding providers."""

from galmuri.retrieval.embeddings.configuration import EmbeddingConfig
from galmuri.retrieval.embeddings.fastembed import FastEmbedEmbedding
from galmuri.retrieval.embeddings.openai import OpenAIEmbedding

__all__ = ["EmbeddingConfig", "FastEmbedEmbedding", "OpenAIEmbedding"]
