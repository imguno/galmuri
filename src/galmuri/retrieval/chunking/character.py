"""Bounded Unicode character windows with explicit overlap."""

from dataclasses import dataclass

from galmuri.retrieval.models import Chunk
from galmuri.retrieval.ports import Chunker
from galmuri.retrieval.validation import positive_int


@dataclass(frozen=True)
class CharacterChunker(Chunker):
    size: int = 800
    overlap: int = 80

    def __post_init__(self):
        positive_int(self.size, "size")
        if type(self.overlap) is not int or not 0 <= self.overlap < self.size:
            raise ValueError("overlap must be a nonnegative integer smaller than size")

    @property
    def identity(self) -> str:
        return f"character:v1:{self.size}:{self.overlap}"

    def split(self, text: str) -> tuple[Chunk, ...]:
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.size, len(text))
            chunks.append(Chunk(text[start:end], start, end))
            if end == len(text):
                break
            start = end - self.overlap
        return tuple(chunks)
