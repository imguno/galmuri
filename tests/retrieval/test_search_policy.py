"""Query extension results remain subordinate to publication and live permissions."""

from dataclasses import replace
from itertools import repeat

import pytest

from galmuri.retrieval import ReciprocalRankFusion, SearchCandidate, SearchConfig
from galmuri.retrieval.errors import ProviderError
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import DEV, fixture


def configured(tmp_path, policy):
    runtime, source, embedding, store = fixture(tmp_path)
    app = replace(
        runtime.apps["sample"], retrieval=replace(runtime.apps["sample"].retrieval, search=policy)
    )
    runtime = Runtime(runtime.database.path, [app])
    runtime.sync()
    return runtime, source, embedding, store


def test_weighted_rrf_changes_ranking_without_comparing_score_scales():
    rankings = {
        "lexical": (SearchCandidate("a", 2000), SearchCandidate("b", 1000)),
        "vector": (SearchCandidate("b", 0.9), SearchCandidate("a", 0.8)),
    }
    assert ReciprocalRankFusion(lexical_weight=2)(rankings)[0].key == "a"
    assert ReciprocalRankFusion(vector_weight=2)(rankings)[0].key == "b"
    assert ReciprocalRankFusion(lexical_weight=0)(rankings)[0].key == "b"


def test_fusion_change_preserves_vector_generation_and_embedding_cache(tmp_path):
    runtime, _, embedding, _ = fixture(tmp_path)
    runtime.sync()
    before = runtime.search("sample", "content", DEV)[0]
    config = replace(
        runtime.apps["sample"].retrieval,
        search=SearchConfig(fusion=ReciprocalRankFusion(k=10, lexical_weight=2)),
    )
    fresh = Runtime(runtime.database.path, [replace(runtime.apps["sample"], retrieval=config)])
    after = fresh.search("sample", "content", DEV, mode="hybrid")[0]
    assert before["build"] == after["build"]
    assert before["fingerprint"] == after["fingerprint"]
    assert after["score"] == 3 / 11
    assert embedding.calls == 1


def test_custom_lexical_returns_only_ids_and_authoritative_text_is_loaded(tmp_path):
    calls = []

    def lookup(query, *, app, limit):
        calls.append((query, app, limit))
        return [SearchCandidate("not-published", 10), SearchCandidate("doc", 2)]

    runtime, _, _, _ = configured(tmp_path, SearchConfig(lexical=lookup))
    result = runtime.search("sample", "unrelated", DEV, mode="lexical", limit=2)
    assert [item["key"] for item in result] == ["doc"]
    assert result[0]["text"] == "content version 1"
    assert calls == [("unrelated", "sample", 2)]


@pytest.mark.parametrize("effect", ["permissions", "source", "reindex", "configuration"])
def test_fusion_callbacks_cannot_return_stale_or_revoked_content(tmp_path, effect):
    def fusion(rankings):
        assert tuple(rankings) == ("lexical", "vector")
        with pytest.raises(TypeError):
            rankings["lexical"] = ()
        if effect == "permissions":
            runtime.documents.set_permissions("sample", "doc", (), ())
        elif effect == "source":
            source.version = "2"
            runtime.collect("sample", force=True)
        elif effect == "reindex":
            runtime.indexing.reindex("sample")
        else:
            app = runtime.apps["sample"]
            Runtime(
                runtime.database.path,
                [replace(app, retrieval=replace(app.retrieval, revision="2"))],
                activate=True,
            )
        yield SearchCandidate("doc", 1)

    runtime, source, _, _ = configured(tmp_path, SearchConfig(fusion=fusion))
    if effect == "configuration":
        with pytest.raises(ValueError, match="no longer active"):
            runtime.search("sample", "content", DEV, mode="hybrid")
    else:
        assert runtime.search("sample", "content", DEV, mode="hybrid") == []


@pytest.mark.parametrize(
    "producer",
    [
        lambda **kw: repeat(SearchCandidate("doc", 1)),
        lambda **kw: [SearchCandidate("doc", 1), SearchCandidate("doc", 1)],
        lambda **kw: [{"key": "doc", "score": 1, "text": "untrusted"}],
        lambda **kw: [SearchCandidate("a", 1), SearchCandidate("b", 2)],
    ],
)
def test_bad_or_unbounded_candidate_producers_fail_explicitly(tmp_path, producer):
    def lookup(query, **kwargs):
        return producer(**kwargs)

    runtime, _, _, _ = configured(tmp_path, SearchConfig(lexical=lookup))
    with pytest.raises(ProviderError):
        runtime.search("sample", "query", DEV, mode="lexical", limit=2)


def test_fusion_cannot_invent_candidates(tmp_path):
    runtime, _, _, _ = configured(
        tmp_path, SearchConfig(fusion=lambda rankings: [SearchCandidate("invented", 1)])
    )
    with pytest.raises(ProviderError):
        runtime.search("sample", "content", DEV, mode="hybrid")


def test_lexical_search_does_not_load_the_entire_document_corpus(tmp_path, monkeypatch):
    runtime, _, _, _ = fixture(tmp_path)
    runtime.sync()
    query = runtime.indexing.queries
    original = query.visible

    def visible(app, principal, keys=None):
        assert keys is not None, "Lexical mode requested every document body"
        return original(app, principal, keys=keys)

    monkeypatch.setattr(query, "visible", visible)
    assert runtime.search("sample", "content", DEV, mode="lexical")[0]["key"] == "doc"


def test_candidate_window_applies_to_vector_results_given_to_fusion(tmp_path, monkeypatch):
    received = []

    def fusion(rankings):
        received.append({name: len(items) for name, items in rankings.items()})
        return ReciprocalRankFusion()(rankings)

    runtime, _, _, _ = configured(tmp_path, SearchConfig(fusion=fusion, candidate_limit=1))
    query = runtime.indexing.queries
    original = query.semantic
    # The vector neighbor search overfetches chunks; orchestration must cap documents.
    monkeypatch.setattr(query, "semantic", lambda *args: original(*args) * 10)
    assert runtime.search("sample", "content", DEV, mode="hybrid")
    assert received == [{"lexical": 1, "vector": 1}]
