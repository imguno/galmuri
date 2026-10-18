"""Ingestion returns prepared documents, not instructions to defer Python calls."""

from dataclasses import dataclass

from galmuri.contracts.documents import Document


@dataclass(frozen=True)
class IngestResult:
    """Prepared documents and diagnostic messages returned by an ingestion handler."""

    documents: tuple[Document, ...]
    messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        keys = [document.key for document in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("A file result cannot contain duplicate document identities")


# Preserve existing imports and isinstance checks without introducing another contract.
Processed = IngestResult
