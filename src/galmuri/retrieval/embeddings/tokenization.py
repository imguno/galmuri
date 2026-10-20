"""Isolate FastEmbed's tokenizer adapter; never alter its shared inference tokenizer."""

import hashlib
import json
from dataclasses import dataclass

from galmuri.retrieval.chunking import TokenBudgetChunker
from galmuri.retrieval.errors import ProviderError
from galmuri.retrieval.ports import Chunker


def token_budget(model):
    """FastEmbed 0.9 ONNX models expose their configured tokenizer on .model."""
    from tokenizers import Tokenizer

    tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
    truncation = getattr(tokenizer, "truncation", None)
    if tokenizer is None or not truncation:
        raise ProviderError(
            "This FastEmbed implementation has no supported tokenizer budget; "
            "use an explicit embedding adapter with a matching tokenizer"
        )
    limit = truncation["max_length"]
    if type(limit) is not int or limit < 1:
        raise ProviderError("FastEmbed tokenizer returned an invalid input limit")
    # Full counts include special tokens. FastEmbed.token_count() itself truncates.
    counter = Tokenizer.from_str(tokenizer.to_str())
    counter.no_truncation()
    counter.no_padding()
    return counter, limit


@dataclass(frozen=True)
class ModelChunker(Chunker):
    embedding: object
    base: Chunker

    @property
    def identity(self):
        encoded = json.dumps(
            [self.base.identity, self.embedding.model, self.embedding.spec.revision],
            ensure_ascii=True,
        )
        return "fastembed-token-budget:v1:" + hashlib.sha256(encoded.encode()).hexdigest()

    def split(self, text):
        tokenizer, limit = self.embedding._token_budget()
        return TokenBudgetChunker(
            self.base,
            lambda value: len(tokenizer.encode(self.embedding.passage_prefix + value).ids),
            limit,
            identity=self.identity,
        ).split(text)
