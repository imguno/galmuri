"""Build document services with replaceable sources, processing, and interfaces."""

from galmuri.apps.definition import App
from galmuri.apps.storage import DatabaseConfig
from galmuri.contracts.documents import Document, Principal
from galmuri.contracts.files import Change, ChangeSet, File, FileRef
from galmuri.contracts.results import IngestResult, Processed
from galmuri.ingestion.configuration import IngestConfig
from galmuri.parsing.configuration import ParsingConfig
from galmuri.processing import Pipeline, Step, process_default
from galmuri.retrieval.chunking.configuration import ChunkingConfig
from galmuri.retrieval.config import RetrievalConfig
from galmuri.retrieval.embeddings.configuration import EmbeddingConfig

__all__ = [
    "App",
    "Change",
    "ChangeSet",
    "ChunkingConfig",
    "DatabaseConfig",
    "Document",
    "EmbeddingConfig",
    "File",
    "FileRef",
    "IngestResult",
    "IngestConfig",
    "ParsingConfig",
    "Pipeline",
    "Principal",
    "Processed",
    "RetrievalConfig",
    "Step",
    "process_default",
]
