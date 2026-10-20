"""Document grant defaults belong to ingestion, never to source credentials."""

import hashlib
import json
from dataclasses import dataclass

from galmuri.contracts.grants import normalize_grants


def _grants(values, name):
    if values is None:
        return None
    try:
        return normalize_grants(values)
    except TypeError:
        raise TypeError(f"{name} must be a collection of nonempty grant strings") from None


@dataclass(frozen=True)
class IngestConfig:
    readers: tuple[str, ...] | None = None
    writers: tuple[str, ...] | None = None
    revision: str = "1"

    def __post_init__(self):
        object.__setattr__(self, "readers", _grants(self.readers, "readers"))
        object.__setattr__(self, "writers", _grants(self.writers, "writers"))
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("Ingestion revision must be a nonempty string")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps([self.readers, self.writers, self.revision], ensure_ascii=True).encode()
        ).hexdigest()
