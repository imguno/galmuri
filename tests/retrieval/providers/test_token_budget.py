"""Use a real tokenizer with a tiny limit to prove no suffix is silently dropped."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from galmuri.retrieval import (
    CharacterChunker,
    EmbeddingConfig,
    EmbeddingSpec,
    FastEmbedEmbedding,
    RetrievalConfig,
)
from galmuri.retrieval.errors import ProviderError
from tests.retrieval.test_projection import Embedding, Store


def provider(limit=6, **options):
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "[CLS]": 1, "[SEP]": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    tokenizer.enable_truncation(max_length=limit)
    tokenizer.enable_padding(length=limit)
    calls = []

    class LocalEmbedding(FastEmbedEmbedding):
        @property
        def spec(self):
            return EmbeddingSpec("test", self.model, 2, str(limit))

    embedding = LocalEmbedding(**options)
    embedding._model = SimpleNamespace(
        model=SimpleNamespace(tokenizer=tokenizer),
        passage_embed=lambda texts: calls.extend(texts) or iter((1, 0) for _ in texts),
        query_embed=lambda text: calls.append(text) or iter(((1, 0),)),
    )
    return embedding, tokenizer, calls


def test_default_splits_full_korean_text_inside_real_model_budget():
    embedding, original, calls = provider()
    config = RetrievalConfig(embedding, Store())
    assert embedding._budget is None
    text = "# 문서\n\n" + "문서 검색 권한 계정 그룹 색인 " * 40 + "마지막 중요 단서"
    chunks = tuple(config.chunker.split(text))
    covered = set()
    counter, limit = embedding._token_budget()
    for chunk in chunks:
        assert chunk.text == text[chunk.start : chunk.end]
        covered.update(range(chunk.start, chunk.end))
        assert len(counter.encode(chunk.text).ids) <= limit
    assert covered == set(range(len(text)))
    assert "단서" in chunks[-1].text
    embedding.embed_documents(tuple(chunk.text for chunk in chunks))
    assert calls[-1] == chunks[-1].text
    assert original.truncation["max_length"] == 6
    assert original.padding["length"] == 6
    assert counter.truncation is None and counter.padding is None


def test_explicit_oversized_chunks_and_queries_fail_instead_of_silent_truncation():
    embedding, _, calls = provider()
    for invoke in (
        lambda: embedding.embed_documents(("one two three four five six",)),
        lambda: embedding.embed_query("one two three four five six"),
    ):
        with pytest.raises(ProviderError, match="token budget"):
            invoke()
    assert not calls


def test_prefix_tokens_consume_budget_and_use_distinct_model_paths():
    embedding, _, calls = provider(passage_prefix="passage: ", query_prefix="query: ")
    text = "문서 검색 설명 내용 마지막 단서"
    chunks = tuple(RetrievalConfig(embedding, Store()).chunker.split(text))
    embedding.embed_documents(tuple(chunk.text for chunk in chunks))
    embedding.embed_query("검색")
    assert all(value.startswith("passage: ") for value in calls[:-1])
    assert calls[-1] == "query: 검색"
    assert FastEmbedEmbedding().spec != FastEmbedEmbedding(passage_prefix="passage: ").spec


def test_replacing_embedding_rebinds_only_automatic_chunker():
    first, _, _ = provider(6)
    second, _, _ = provider(4)
    original = RetrievalConfig(first, Store())
    revised = replace(original, embedding=second)
    assert revised.chunker.embedding is second
    assert revised.chunker.identity != original.chunker.identity
    plain = replace(original, embedding=Embedding())
    assert not hasattr(plain.chunker, "embedding")
    explicit = replace(original, chunker=CharacterChunker(20, 0))
    assert replace(explicit, embedding=second).chunker is explicit.chunker


def test_provider_binding_retains_lazy_token_budget_and_rebinds_after_replacement():
    first, _, first_calls = provider(6)
    second, _, second_calls = provider(4)
    wrapped_first = EmbeddingConfig.from_provider(first)
    config = RetrievalConfig(wrapped_first, Store())
    assert first._budget is None
    assert config.chunker.embedding is first
    text = "one two three four five six seven eight nine ten"
    chunks = tuple(config.chunker.split(text))
    wrapped_first.embed_documents(tuple(chunk.text for chunk in chunks))
    assert len(chunks) > 1
    first_count = len(first_calls)

    wrapped_second = EmbeddingConfig.from_provider(second)
    revised = replace(config, embedding=wrapped_second)
    assert second._budget is None
    assert revised.chunker.embedding is second
    assert revised.chunker.identity != config.chunker.identity
    chunks = tuple(revised.chunker.split(text))
    wrapped_second.embed_documents(tuple(chunk.text for chunk in chunks))
    assert second_calls and len(first_calls) == first_count

    explicit = replace(config, chunker=CharacterChunker(2, 0))
    assert replace(explicit, embedding=wrapped_second).chunker is explicit.chunker


def test_plain_function_binding_keeps_base_chunker_without_provider_policy():
    provider_spec = EmbeddingSpec("test", "functions", 2, "1")

    def documents(texts):
        return tuple((1, 0) for _ in texts)

    def query(text):
        return (1, 0)

    embedding = EmbeddingConfig(documents, query, provider_spec)
    config = RetrievalConfig(embedding, Store())
    assert not hasattr(config.chunker, "embedding")
    assert embedding.embed_documents(("plain",)) == ((1.0, 0.0),)
