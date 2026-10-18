"""Translate provider descriptions without interpreting their opaque addresses."""

import hashlib
import json
from dataclasses import asdict

from duru import ResourceInfo

from galmuri.contracts.files import FileRef


def reference(info: ResourceInfo) -> FileRef:
    if info.kind != "file":
        raise ValueError("Only file resources can be processed")
    if not info.revision:
        raise ValueError("Processing requires a provider content revision")
    # Names and metadata can affect parser selection and document grants. A
    # content-only revision must not hide a rename from the ingestion boundary.
    encoded = json.dumps(asdict(info), sort_keys=True, separators=(",", ":"), allow_nan=False)
    version = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return FileRef(
        info.uri,
        version,
        {
            **info.metadata,
            "name": info.name,
            "media_type": info.media_type,
            "size": info.size,
            "resource_revision": info.revision,
        },
    )
