"""Portable observations owned by ingestion, scoped to one source identity."""

import hashlib
import json

from galmuri.contracts.files import FileRef


class Snapshots:
    def __init__(self, root: object) -> None:
        self.identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()

    def load(self, checkpoint: str | None) -> dict[str, FileRef]:
        if checkpoint is None:
            return {}
        try:
            value = json.loads(checkpoint)
            if value["format"] != 1 or value["source"] != self.identity:
                raise ValueError("Checkpoint belongs to a different source or format")
            references = {}
            for key, record in value["files"].items():
                if (
                    not isinstance(key, str)
                    or not isinstance(record["version"], str)
                    or not isinstance(record["metadata"], dict)
                ):
                    raise ValueError("Invalid source checkpoint reference")
                references[key] = FileRef(key, record["version"], record["metadata"])
            return references
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid source checkpoint") from error

    def dump(self, references: dict[str, FileRef]) -> str:
        return json.dumps(
            {
                "format": 1,
                "source": self.identity,
                "files": {
                    key: {"version": ref.version, "metadata": ref.metadata}
                    for key, ref in references.items()
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
