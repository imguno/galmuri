"""A query with no accessible vector publication must not perform external inference."""

import pytest

from galmuri import Principal
from tests.retrieval.test_projection import DEV, fixture


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
@pytest.mark.parametrize("state", ["empty", "denied", "pending", "stale", "deleted"])
def test_ineligible_corpus_never_calls_embedding_or_store(tmp_path, monkeypatch, mode, state):
    runtime, source, embedding, store = fixture(tmp_path)
    if state == "pending":
        store.fail = True
    if state != "empty":
        runtime.sync()
    if state in {"stale", "deleted"}:
        source.version = "2"
        source.deleted = state == "deleted"
        runtime.collect("sample", force=True)

    def unexpected(*args):
        pytest.fail("No accessible publication exists; external IO must not run")

    monkeypatch.setattr(embedding, "embed_query", unexpected)
    monkeypatch.setattr(store, "ensure", unexpected)
    principal = Principal() if state == "denied" else DEV
    result = runtime.search("sample", "content", principal, mode=mode)
    # A pending vector upload still leaves its accepted lexical document searchable.
    assert [item["key"] for item in result] == (
        ["doc"] if state == "pending" and mode == "hybrid" else []
    )


def test_permission_is_checked_again_when_revoked_during_query_embedding(tmp_path, monkeypatch):
    runtime, _, embedding, store = fixture(tmp_path)
    runtime.sync()

    def revoke(query):
        runtime.documents.set_permissions("sample", "doc", (), ())
        return (1.0, 0.1)

    monkeypatch.setattr(embedding, "embed_query", revoke)
    assert runtime.search("sample", "content", DEV, mode="vector") == []
    assert store.allowed is None
