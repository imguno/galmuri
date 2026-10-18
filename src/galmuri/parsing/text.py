"""Decode a versioned input into the default document boundary value."""

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File


def parse_text(file: File, *, encoding: str = "utf-8-sig") -> tuple[Document, ...]:
    text = file.content.decode(encoding)
    if "\0" in text:
        raise ValueError("Binary content requires an explicit custom parser")
    metadata = {
        **file.ref.metadata,
        "source_key": file.ref.key,
        "source_version": file.ref.version,
        "format": "text",
    }
    return (Document(file.ref.key, text, metadata),)
