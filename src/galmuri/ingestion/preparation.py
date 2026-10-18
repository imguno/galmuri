"""Project documents without publishing unaccepted worker results."""

import json
from collections.abc import Iterable
from dataclasses import replace

from galmuri.contracts.documents import Document, DocumentContract
from galmuri.contracts.results import IngestResult


def _grants(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError("Permissions must be a collection of grant strings")
    grants = tuple(values)
    if not all(isinstance(value, str) and value for value in grants):
        raise TypeError("Permission grants must be nonempty strings")
    return tuple(dict.fromkeys(grants))


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
    read_grants = None if readers is None else _grants(readers)
    write_grants = None if writers is None else _grants(writers)
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
                readers=_grants(document.readers) if read_grants is None else read_grants,
                writers=_grants(document.writers) if write_grants is None else write_grants,
            )
        )
    return IngestResult(tuple(prepared))
