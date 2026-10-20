"""Source acceptance and document publication configuration."""

from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.handler import IngestHandler
from galmuri.ingestion.preparation import prepare_documents

__all__ = ["IngestConfig", "IngestHandler", "prepare_documents"]
