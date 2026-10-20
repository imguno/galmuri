"""Bind a document splitting function without taking over its execution lifecycle."""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from galmuri.contracts.callables import callable_identity, callable_location
from galmuri.retrieval.chunking.structure import StructureChunker
from galmuri.retrieval.models import Chunk
from galmuri.retrieval.ports import Chunker
from galmuri.retrieval.validation import label


@dataclass(frozen=True, init=False)
class ChunkingConfig(Chunker):
    process: Callable[[str], Iterable[Chunk]]
    revision: str
    _identity: str

    def __init__(self, process=None, *, identity=None, revision="1"):
        if process is None:
            default = StructureChunker()
            process = default.split
            if identity is None:
                identity = default.identity
        label(revision, "chunker revision")
        selected = callable_identity(process, identity)
        value = json.dumps([selected, callable_location(process), revision], ensure_ascii=True)
        object.__setattr__(self, "process", process)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(
            self, "_identity", "callable-chunker:" + hashlib.sha256(value.encode()).hexdigest()
        )

    @property
    def identity(self) -> str:
        return self._identity

    def split(self, text: str) -> Iterable[Chunk]:
        """The indexing boundary bounds and checks the returned exact-text anchors."""
        if not isinstance(text, str):
            raise TypeError("Chunking input must be text")
        return self.process(text)

    @classmethod
    def from_chunker(cls, chunker: Chunker, *, revision="1"):
        """Explicitly bind a configured instance; its identity covers its options."""
        identity = getattr(chunker, "identity", None)
        label(identity, "chunker identity")
        return cls(chunker.split, identity=identity, revision=revision)
