"""Project documents without publishing unaccepted worker results."""

import json
from collections.abc import Iterable
from dataclasses import replace

from galmuri.contracts.documents import Document, DocumentContract
from galmuri.contracts.grants import normalize_grants
from galmuri.contracts.results import IngestResult


def prepare_documents(
    documents: Iterable[object],
    *,
    contract: DocumentContract | None = None,
    readers: Iterable[str] | None = None,
    writers: Iterable[str] | None = None,
) -> IngestResult:
    """Prepare a complete file result for runtime's guarded publication.

    This function executes immediately. It does not defer Python calls, expose
    a mutable external index, invent embeddings, or make permissions public.
    Custom data is projected at this explicit boundary using its own contract.
    """
    read_grants = None if readers is None else normalize_grants(readers)
    write_grants = None if writers is None else normalize_grants(writers)
    prepared = []
    for value in documents:
        document = contract.project(value) if contract is not None else value
        if not isinstance(document, Document):
            raise TypeError("Custom document values require a DocumentContract projection")
        if not isinstance(document.key, str) or not isinstance(document.text, str):
            raise TypeError("Document identity and text must be strings")
        if not isinstance(document.metadata, dict):
            raise TypeError("Document metadata must be a dictionary")
        # Freeze a serializable snapshot instead of retaining caller-owned lists.
        metadata = json.loads(json.dumps(document.metadata, allow_nan=False))
        prepared.append(
            replace(
                document,
                metadata=metadata,
                readers=normalize_grants(document.readers) if read_grants is None else read_grants,
                writers=normalize_grants(document.writers)
                if write_grants is None
                else write_grants,
            )
        )
    return IngestResult(tuple(prepared))
