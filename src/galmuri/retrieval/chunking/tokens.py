"""Apply a caller-owned tokenizer budget to exact anchored chunks."""

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from galmuri.retrieval.models import Chunk
from galmuri.retrieval.ports import Chunker
from galmuri.retrieval.validation import label, positive_int


@dataclass(frozen=True, init=False)
class TokenBudgetChunker(Chunker):
    """Keep base boundaries where possible; subdivide only over-budget spans.

    The counter must measure the complete input without truncation, including any
    special tokens or prefixes used during embedding. ``identity`` identifies that
    counting policy and tokenizer revision. Counting runs only during ``split``.
    Binary subdivision does not assume token counts increase monotonically with
    text length. Existing base overlap is retained; no synthetic text is added.
    """

    base: Chunker
    count_tokens: Callable[[str], int]
    max_tokens: int
    _identity: str

    def __init__(self, base, count_tokens, max_tokens, *, identity):
        positive_int(max_tokens, "max_tokens")
        label(identity, "token counter identity")
        label(getattr(base, "identity", None), "base chunker identity")
        if not callable(getattr(base, "split", None)):
            raise TypeError("Base chunker must implement split")
        if not callable(count_tokens):
            raise TypeError("Token counter must be callable")
        value = json.dumps([base.identity, identity, max_tokens], ensure_ascii=True)
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "count_tokens", count_tokens)
        object.__setattr__(self, "max_tokens", max_tokens)
        object.__setattr__(
            self, "_identity", "token-budget:v1:" + hashlib.sha256(value.encode()).hexdigest()
        )

    @property
    def identity(self) -> str:
        return self._identity

    def split(self, text: str) -> Iterator[Chunk]:
        if not isinstance(text, str):
            raise TypeError("Chunking input must be text")
        for chunk in self.base.split(text):
            if (
                not isinstance(chunk, Chunk)
                or not 0 <= chunk.start < chunk.end <= len(text)
                or text[chunk.start : chunk.end] != chunk.text
            ):
                raise ValueError("Base chunk anchors must match the exact document text")
            pending = [chunk]
            while pending:
                current = pending.pop()
                count = self.count_tokens(current.text)
                if type(count) is not int or count < 0:
                    raise ValueError("Token counter must return a nonnegative integer")
                if count <= self.max_tokens:
                    yield current
                    continue
                if len(current.text) == 1:
                    raise ValueError("A single Unicode code point exceeds the token budget")
                middle = current.start + len(current.text) // 2
                pending.extend(
                    (
                        Chunk(text[middle : current.end], middle, current.end),
                        Chunk(text[current.start : middle], current.start, middle),
                    )
                )
