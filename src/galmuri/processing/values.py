"""Only bounded, validated file/document/result snapshots cross a step boundary."""

import base64
import json
from dataclasses import asdict
from itertools import islice

from galmuri.contracts.files import File, FileRef
from galmuri.contracts.results import IngestResult
from galmuri.ingestion.preparation import prepare_documents

MAX_DOCUMENTS = 10_000
MAX_MESSAGES = 1_000


def _bounded(values, maximum, name):
    if isinstance(values, (str, bytes, dict)):
        raise TypeError(f"{name} must be an iterable of contract values")
    values = tuple(islice(iter(values), maximum + 1))
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds the {maximum} item boundary limit")
    return values


def snapshot(kind, value):
    if kind == "file":
        if not isinstance(value, File) or not isinstance(value.content, bytes):
            raise TypeError("File steps must return File with bytes content")
        ref = value.ref
        if not isinstance(ref, FileRef) or not all(
            isinstance(item, str) and item for item in (ref.key, ref.version)
        ):
            raise TypeError("File steps require a valid FileRef")
        if not isinstance(ref.metadata, dict):
            raise TypeError("File metadata must be a dictionary")
        metadata = json.loads(json.dumps(ref.metadata, allow_nan=False))
        return File(FileRef(ref.key, ref.version, metadata), value.content)
    if kind == "documents":
        return prepare_documents(_bounded(value, MAX_DOCUMENTS, "Documents")).documents
    if kind == "result":
        if not isinstance(value, IngestResult):
            raise TypeError("Result steps must return IngestResult")
        documents = snapshot("documents", value.documents)
        messages = _bounded(value.messages, MAX_MESSAGES, "Messages")
        if any(not isinstance(message, str) for message in messages):
            raise TypeError("IngestResult messages must be strings")
        return IngestResult(documents, messages)
    raise ValueError("Unknown processing boundary")


def encode(kind, value):
    value = snapshot(kind, value)
    if kind == "file":
        payload = {"ref": asdict(value.ref), "content": base64.b64encode(value.content).decode()}
    elif kind == "documents":
        payload = [asdict(document) for document in value]
    else:
        payload = asdict(value)
    return json.dumps(payload, allow_nan=False)


def decode(kind, payload):
    from galmuri.contracts.documents import Document

    value = json.loads(payload)
    if kind == "file":
        value = File(FileRef(**value["ref"]), base64.b64decode(value["content"], validate=True))
    elif kind == "documents":
        value = tuple(Document(**document) for document in value)
    elif kind == "result":
        value = IngestResult(
            tuple(Document(**document) for document in value["documents"]), value["messages"]
        )
    return snapshot(kind, value)
