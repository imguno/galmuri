"""Immutable data exchanged by retrieval collaborators."""

from dataclasses import dataclass

from galmuri.retrieval.validation import label, positive_int


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimensions: int
    revision: str

    def __post_init__(self):
        for name in ("provider", "model", "revision"):
            label(getattr(self, name), name)
        positive_int(self.dimensions, "dimensions")


@dataclass(frozen=True)
class Chunk:
    """Unicode codepoint offsets into the exact stored document text."""

    text: str
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("chunk offsets must be integers")
        if self.start < 0 or self.end < self.start or self.end - self.start != len(self.text):
            raise ValueError("chunk offsets must match its text length")


@dataclass(frozen=True)
class VectorPoint:
    id: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
