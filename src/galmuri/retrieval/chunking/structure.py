"""Pack exact-text blocks within sections, splitting only oversized blocks."""

from dataclasses import dataclass

from galmuri.parsing.structure import markdown_blocks
from galmuri.retrieval.chunking.character import CharacterChunker
from galmuri.retrieval.models import Chunk
from galmuri.retrieval.ports import Chunker


@dataclass(frozen=True)
class StructureChunker(Chunker):
    """Bounded character spans respecting Markdown sections and paragraphs.

    Short paragraphs and fenced blocks remain whole when they fit ``size``.
    Oversized blocks use character windows with ``overlap``; overlap never
    crosses a block or section boundary. Heading text is not prepended to later
    chunks, so every result retains an exact anchor into the stored document.

    ``size`` counts Unicode code points, not model tokens. Use a tokenizer-aware
    custom Chunker when a model-specific token budget must be guaranteed.
    """

    size: int = 800
    overlap: int = 80

    def __post_init__(self):
        # Share validation with the explicit fixed-window alternative.
        CharacterChunker(self.size, self.overlap)

    @property
    def identity(self) -> str:
        return f"structure:v1:{self.size}:{self.overlap}"

    def split(self, text: str) -> tuple[Chunk, ...]:
        if not isinstance(text, str):
            raise TypeError("Chunking input must be text")
        chunks = []
        pending_start = pending_end = 0
        fallback = CharacterChunker(self.size, self.overlap)
        for block in markdown_blocks(text):
            if pending_end > pending_start and (
                block.level or block.end - pending_start > self.size
            ):
                chunks.append(Chunk(text[pending_start:pending_end], pending_start, pending_end))
                pending_start = pending_end
            if block.end - block.start > self.size:
                chunks.extend(
                    Chunk(chunk.text, block.start + chunk.start, block.start + chunk.end)
                    for chunk in fallback.split(text[block.start : block.end])
                )
                pending_start = pending_end = block.end
            else:
                if pending_start == pending_end:
                    pending_start = block.start
                pending_end = block.end
        if pending_end > pending_start:
            chunks.append(Chunk(text[pending_start:pending_end], pending_start, pending_end))
        return tuple(chunks)
