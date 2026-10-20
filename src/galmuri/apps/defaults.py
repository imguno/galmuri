"""The beginner App preset is local and requires no server or paid API key."""

import os
from dataclasses import replace
from pathlib import Path


class _AutomaticRetrieval:
    def __repr__(self):
        return "AUTO_RETRIEVAL"


AUTO_RETRIEVAL = _AutomaticRetrieval()


def resolve_retrieval(database: str | Path, store=None, *, config=None):
    """Fill only omitted providers, after project DB selection and before activation."""
    from galmuri.retrieval import FastEmbedEmbedding, RetrievalConfig, SQLiteVectorStore

    directory = Path(database).resolve().parent
    config = RetrievalConfig() if config is None else config
    embedding = config.embedding
    if embedding is None:
        embedding = FastEmbedEmbedding(
            model=os.environ.get(
                "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            ),
            cache_dir=os.environ.get("EMBEDDING_CACHE", str(directory / "models")),
        )
    selected_store = config.store if config.store is not None else store
    if selected_store is None:
        selected_store = SQLiteVectorStore(directory / "vectors.sqlite3")
    return replace(config, embedding=embedding, store=selected_store, mode=config.mode or "hybrid")
