"""Built-in ingestion composes parsing and document preparation explicitly."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File
from galmuri.contracts.results import IngestResult
from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.preparation import prepare_documents
from galmuri.parsing.configuration import ParsingConfig


@dataclass(frozen=True)
class IngestHandler:
    parsing: ParsingConfig
    config: IngestConfig
    durable_ingestion: ClassVar[bool] = True

    def __post_init__(self):
        if self.config.readers is None or self.config.writers is None:
            raise ValueError("Resolve ingestion permission defaults before constructing a handler")

    @property
    def fingerprint(self) -> str:
        value = f"{self.parsing.fingerprint}:{self.config.fingerprint}"
        return hashlib.sha256(value.encode()).hexdigest()

    def parse(self, file: File) -> tuple[Document, ...]:
        # Snapshot/validate custom output at the parser contract, before checkpointing it.
        return prepare_documents(self.parsing.parser(file)).documents

    def prepare(self, documents: Iterable[Document]) -> IngestResult:
        return prepare_documents(
            documents, readers=self.config.readers, writers=self.config.writers
        )

    def __call__(self, file: File) -> IngestResult:
        return self.prepare(self.parse(file))
