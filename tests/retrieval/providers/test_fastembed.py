"""Model collaborator tests; actual neural acceptance runs separately in Docker."""

import sys
from types import SimpleNamespace

import pytest

from galmuri.retrieval import FastEmbedEmbedding


def test_optional_model_is_lazy_and_uses_distinct_passage_query_paths(monkeypatch, tmp_path):
    calls = []

    class Model:
        @classmethod
        def get_embedding_size(cls, model):
            return 2

        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def passage_embed(self, texts):
            calls.append(("passages", texts))
            return iter((1, 0) for _ in texts)

        def query_embed(self, text):
            calls.append(("query", text))
            return iter(((0, 1),))

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Model))
    provider = FastEmbedEmbedding(cache_dir=tmp_path, threads=1)
    assert not calls
    assert provider.spec.dimensions == 2
    assert not calls
    assert provider.embed_documents(()) == ()
    assert provider.embed_documents(("a", "b")) == ((1.0, 0.0), (1.0, 0.0))
    assert provider.embed_query("q") == (0.0, 1.0)
    assert [call[0] for call in calls] == ["init", "passages", "query"]
    assert calls[0][1]["threads"] == 1
    assert calls[0][1]["providers"] == ["CPUExecutionProvider"]


def test_missing_optional_dependency_is_explicit(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)
    provider = FastEmbedEmbedding()
    with pytest.raises(RuntimeError, match="install galmuri"):
        _ = provider.spec
