"""Compatibility alias for document preparation; this does not build a vector index."""

from galmuri.ingestion.preparation import prepare_documents as index_default

__all__ = ["index_default"]
