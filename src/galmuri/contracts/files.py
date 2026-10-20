"""Source references remain serializable across worker processes."""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from duru import Conflict as SourceConflict
from duru import EffectUnknown

__all__ = ["Change", "ChangeSet", "EffectUnknown", "File", "FileRef", "SourceConflict"]


@dataclass(frozen=True)
class FileRef:
    key: str
    version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.version:
            raise ValueError("File identity and version must be nonempty")

    @property
    def name(self) -> str:
        # A URI is an opaque address, not a path or display name. Old local
        # references retain their relative-path fallback for stored checkpoints.
        name = self.metadata.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise TypeError("Source display name must be a string")
            return name
        return PurePosixPath(self.key).name

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix.lower()


@dataclass(frozen=True)
class File:
    ref: FileRef
    content: bytes

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def read(self) -> bytes:
        return self.content


@dataclass(frozen=True)
class Change:
    ref: FileRef
    deleted: bool = False


@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[Change, ...]
    checkpoint: str | None = None
    complete: bool = True
