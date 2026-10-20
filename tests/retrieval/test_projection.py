"""Deterministic collaborators exercise projection ownership, never model quality."""

import json
import threading
from dataclasses import replace

import pytest

from galmuri import App, Change, ChangeSet, Document, File, FileRef, IngestResult, Principal
from galmuri.retrieval import EmbeddingSpec, RetrievalConfig, VectorMatch
from galmuri.retrieval.indexing.claims import claim
from galmuri.retrieval.indexing.execution import execute
from galmuri.retrieval.indexing.reconciliation import reconcile
from galmuri.runtime import Runtime


class Embedding:
    spec = EmbeddingSpec("test-only", "deterministic", 2, "1")

    def __init__(self):
        self.calls = 0
        self.fail = False

    def embed_documents(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return tuple((1.0, 0.1) for _ in texts)

    def embed_query(self, query):
        return (1.0, 0.1)


class Store:
    identity = "test-memory-store"

    def __init__(self):
        self.points = {}
        self.fail = False
        self.delete_fail = False
        self.on_search = lambda: None
        self.on_upsert = lambda: None
        self.allowed = None
        self.uploads = []

    def ensure(self, namespace, dimensions):
        assert dimensions == 2

    def upsert(self, namespace, points):
        self.uploads.append(tuple(point.id for point in points))
        self.on_upsert()
        if self.fail:
            raise RuntimeError("store unavailable")
        self.points.update({point.id: point for point in points})

    def search(self, namespace, vector, *, allowed_ids, limit):
        self.allowed = allowed_ids
        found = tuple(VectorMatch(key, 0.9) for key in sorted(self.points) if key in allowed_ids)[
            :limit
        ]
        self.on_search()
        return found

    def delete(self, namespace, ids):
        if self.delete_fail:
            raise RuntimeError("delete unavailable")
        for identifier in ids:
            self.points.pop(identifier, None)


class Source:
    identity = "semantic-test-source"

    def __init__(self):
        self.version = "1"
        self.deleted = False

    def changes(self, checkpoint):
        return ChangeSet((Change(FileRef("file", self.version), self.deleted),), self.version)

    def read(self, ref):
        return File(ref, f"content version {self.version}".encode())


def handler(file):
    return IngestResult((Document("doc", file.text, readers=("group:dev",)),))


def fixture(tmp_path, *, config=None, clock=None):
    embed, store, source = Embedding(), Store(), Source()
    config = config or RetrievalConfig(embed, store, retry_delay=0)
    app = App("sample", source, handler, retrieval=config)
    runtime = Runtime(tmp_path / "state.db", [app], **({"clock": clock} if clock else {}))
    return runtime, source, embed, store


DEV = Principal("alice", frozenset({"dev"}))


def test_normal_sync_vector_hybrid_lexical_and_fresh_restart(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    assert runtime.search("sample", "synonym", DEV, mode="lexical") == []
    match = runtime.search("sample", "synonym", DEV)[0]
    assert match["chunks"][0]["text"] == "content version 1"
    assert match["embedding"]["provider"] == "test-only"
    assert runtime.search("sample", "content", DEV, mode="hybrid")[0]["score"] == 2 / 61
    assert runtime.search("sample", "synonym", Principal()) == []
    assert embed.calls == 1
    restarted = Runtime(runtime.database.path, list(runtime.apps.values()))
    assert restarted.search("sample", "anything", DEV)[0]["build"] == match["build"]
    assert restarted.describe("sample", DEV)["search"]["visible_documents"] == 1


def test_store_failure_restart_reuses_prepared_vectors_and_ids(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    store.fail = True
    runtime.sync()
    jobs = runtime.indexing.status()["jobs"]
    assert jobs[-1]["state"] == "FAILED"
    assert jobs[-1]["stage"] == "STORING"
    assert embed.calls == 1
    assert len(set(store.uploads)) == 1
    store.fail = False
    fresh = Runtime(runtime.database.path, list(runtime.apps.values()))
    fresh.indexing.retry(jobs[-1]["id"])
    assert fresh.indexing.work_once("separate-index-worker")
    assert embed.calls == 1
    assert len(set(store.uploads)) == 1
    assert fresh.search("sample", "query", DEV)


def test_source_intent_fence_before_new_body_publication_and_delete(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("sample", force=True)
    assert runtime.read("sample", "doc", DEV)["version"] == "1"
    assert runtime.search("sample", "query", DEV) == []
    runtime.drain()
    assert runtime.search("sample", "query", DEV)[0]["version"] == "2"
    source.deleted = True
    runtime.collect("sample", force=True)
    assert runtime.search("sample", "query", DEV) == []
    runtime.drain()
    assert store.points == {}


def test_acl_before_limit_and_recheck_after_remote_io(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    assert runtime.search("sample", "q", Principal(), limit=1) == []
    assert store.allowed is None
    store.on_search = lambda: runtime.documents.set_permissions("sample", "doc", (), ())
    assert runtime.search("sample", "q", DEV, limit=1) == []
    assert len(store.allowed) == 1


def test_reindex_and_explicit_model_activation_fence_old_runtime(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    first = runtime.search("sample", "q", DEV)[0]["build"]
    response = runtime.indexing.reindex("sample")
    assert response["scheduled"] == 1
    assert runtime.search("sample", "q", DEV) == []
    runtime.drain()
    assert runtime.search("sample", "q", DEV)[0]["build"] != first
    config = replace(runtime.apps["sample"].retrieval, revision="2")
    revised = replace(runtime.apps["sample"], retrieval=config)
    with pytest.raises(ValueError, match="activate"):
        Runtime(runtime.database.path, [revised])
    fresh = Runtime(runtime.database.path, [revised], activate=True)
    with pytest.raises(ValueError, match="no longer active"):
        runtime.search("sample", "q", DEV)
    assert not runtime.indexing.work_once("old")
    assert fresh.search("sample", "q", DEV) == []
    fresh.drain()
    assert fresh.search("sample", "q", DEV)[0]["fingerprint"] == config.fingerprint


def test_durable_reconcile_observes_other_process_publication(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    other = Runtime(runtime.database.path, list(runtime.apps.values()))
    runtime.collect("sample")
    assert runtime.work_once()  # Only body ingestion.
    assert other.indexing.work_once("other")
    assert other.search("sample", "q", DEV)


def test_expired_lease_cannot_activate_and_is_recovered(tmp_path):
    now = [100.0]
    runtime, source, embed, store = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("sample")
    runtime.work_once()
    reconcile(runtime.database, runtime.apps, runtime.clock)
    old = claim(runtime.database, runtime.apps, runtime.clock, "dead")
    now[0] += 61
    new = claim(runtime.database, runtime.apps, runtime.clock, "replacement")
    execute(runtime.database, runtime.apps["sample"], old, runtime.clock)
    assert store.uploads == []
    execute(runtime.database, runtime.apps["sample"], new, runtime.clock)
    assert runtime.search("sample", "q", DEV)


def test_late_upload_after_cleanup_is_deleted_again(tmp_path):
    now = [100.0]
    runtime, source, embed, store = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("sample")
    runtime.work_once()
    entered, release = threading.Event(), threading.Event()

    def block():
        entered.set()
        assert release.wait(10)

    store.on_upsert = block
    thread = threading.Thread(target=lambda: runtime.indexing.work_once("slow"))
    thread.start()
    assert entered.wait(10)
    old = runtime.indexing.status()["jobs"][0]["id"]
    runtime.indexing.reindex("sample")
    now[0] += 61
    # Simulate another process finishing cleanup before the delayed remote upload.
    from galmuri.retrieval.indexing.cleanup import work_once

    assert work_once(runtime.database, runtime.apps, runtime.clock)
    release.set()
    thread.join(10)
    assert not thread.is_alive()
    assert store.points
    status = next(item for item in runtime.indexing.status()["cleanup"] if item["build"] == old)
    assert status["state"] == "READY"
    store.on_upsert = lambda: None
    runtime.drain()
    assert runtime.search("sample", "q", DEV)[0]["build"] != old
    with runtime.database.connection() as connection:
        prepared = json.loads(
            connection.execute(
                "SELECT prepared FROM semantic_builds WHERE id=?", (old,)
            ).fetchone()[0]
        )
    assert all(item["id"] not in store.points for item in prepared)


def test_cleanup_failure_is_durable_and_retryable(tmp_path):
    now = [100.0]
    runtime, source, embed, store = fixture(tmp_path, clock=lambda: now[0])
    runtime.sync()
    store.delete_fail = True
    runtime.indexing.reindex()
    runtime.drain()
    assert runtime.indexing.status()["cleanup"][0]["state"] == "RETRY_WAIT"
    store.delete_fail = False
    now[0] += 10
    runtime.drain()
    assert runtime.indexing.status()["cleanup"][0]["state"] == "SUCCEEDED"


def test_other_store_cleanup_is_not_sent_to_replacement_store(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    other = Store()
    other.identity = "other-store"
    app = replace(runtime.apps["sample"], retrieval=RetrievalConfig(embed, other, retry_delay=0))
    replacement = Runtime(runtime.database.path, [app], activate=True)
    replacement.drain()
    assert replacement.indexing.status()["cleanup"][0]["state"] == "WAITING_STORE"
    replacement = Runtime(runtime.database.path, [app], cleanup_stores=(store,))
    assert replacement.indexing.work_once("retired-store-cleanup")
    assert store.points == {}


def test_embedding_failure_is_separate_from_ingestion_and_retry(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    embed.fail = True
    runtime.sync()
    status = runtime.status()
    assert status["jobs"][0]["state"] == "SUCCEEDED"
    job = status["indexing"]["jobs"][0]
    assert job["state"] == "FAILED"
    assert job["stage"] == "EMBEDDING"
    embed.fail = False
    runtime.indexing.retry(job["id"])
    runtime.drain()
    assert runtime.search("sample", "q", DEV)


def test_pause_stops_new_semantic_claims_until_resume(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.collect("sample")
    runtime.work_once()
    runtime.pause("sample")
    assert not runtime.work_once()
    assert runtime.indexing.status()["jobs"][0]["state"] == "READY"
    runtime.resume("sample")
    assert runtime.work_once()
    assert runtime.search("sample", "q", DEV)


def test_disabling_retrieval_withdraws_and_cleans_up_old_generations(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    lexical = replace(runtime.apps["sample"], retrieval=None)
    fresh = Runtime(runtime.database.path, [lexical], activate=True)
    assert fresh.search("sample", "content", DEV)
    with pytest.raises(ValueError, match="does not configure"):
        fresh.search("sample", "content", DEV, mode="vector")
    fresh.indexing.status()
    fresh = Runtime(runtime.database.path, [lexical], cleanup_stores=(store,))
    assert fresh.indexing.work_once("retired-store-cleanup")
    assert store.points == {}


def test_infinite_custom_embedding_output_is_rejected_without_hang(tmp_path):
    from itertools import repeat

    runtime, source, embed, store = fixture(tmp_path)
    embed.embed_documents = lambda texts: repeat((1.0, 0.1))
    runtime.sync()
    assert runtime.indexing.status()["jobs"][0]["state"] == "FAILED"
    assert store.points == {}


def test_nonfinite_custom_query_scores_are_rejected(tmp_path):
    from galmuri.retrieval import ProviderError

    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    store.search = lambda namespace, vector, **kwargs: (
        VectorMatch(next(iter(store.points)), float("nan")),
    )
    with pytest.raises(ProviderError, match="invalid"):
        runtime.search("sample", "q", DEV)


def test_source_update_during_upload_never_activates_obsolete_content(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    runtime.collect("sample")
    runtime.work_once()

    def change():
        source.version = "2"
        runtime.collect("sample", force=True)

    store.on_upsert = change
    assert runtime.indexing.work_once("index")
    assert runtime.search("sample", "q", DEV) == []
    store.on_upsert = lambda: None
    runtime.drain()
    assert runtime.search("sample", "q", DEV)[0]["version"] == "2"


def test_query_widens_chunk_window_to_find_distinct_document_topk(tmp_path):
    from galmuri.retrieval import CharacterChunker

    embed, store = Embedding(), Store()
    config = RetrievalConfig(embed, store, chunker=CharacterChunker(size=2, overlap=0))
    runtime, source, _, _ = fixture(tmp_path, config=config)
    runtime.apps["sample"] = replace(
        runtime.apps["sample"],
        handler=lambda file: IngestResult(
            (
                Document("a", "a" * 100, readers=("*",)),
                Document("b", "b" * 100, readers=("*",)),
            )
        ),
    )
    runtime.sync()
    assert len(runtime.search("sample", "q", DEV, limit=2)) == 2


def test_failed_config_open_rolls_back_other_app_activation(tmp_path):
    runtime, source, embed, store = fixture(tmp_path)
    app = runtime.apps["sample"]
    added = replace(app, name="new_app")
    mismatch = replace(app, retrieval=replace(app.retrieval, revision="new"))
    with pytest.raises(ValueError, match="activate"):
        Runtime(runtime.database.path, [added, mismatch])
    with runtime.database.connection() as connection:
        assert connection.execute("SELECT 1 FROM app_state WHERE name='new_app'").fetchone() is None
        assert (
            connection.execute("SELECT 1 FROM semantic_configs WHERE app='new_app'").fetchone()
            is None
        )
    runtime.sync()
    assert runtime.search("sample", "q", DEV)


def test_failed_semantic_activation_rolls_back_body_revision_and_publication(tmp_path, monkeypatch):
    from galmuri.execution.persistence import composition

    runtime, source, embed, store = fixture(tmp_path)
    runtime.sync()
    prior = runtime.search("sample", "q", DEV)[0]["build"]

    def fail(connection, apps, *, explicit):
        raise RuntimeError("injected semantic activation failure")

    monkeypatch.setattr(composition, "activate_retrieval", fail)
    with pytest.raises(RuntimeError, match="injected"):
        Runtime(
            runtime.database.path, [replace(runtime.apps["sample"], revision="2")], activate=True
        )
    with runtime.database.connection() as connection:
        assert connection.execute("SELECT revision FROM app_state").fetchone()[0] == "1"
        assert connection.execute("SELECT revision FROM semantic_configs").fetchone()[0] == "1"
        assert connection.execute("SELECT state FROM documents").fetchone()[0] == "ACTIVE"
    assert runtime.search("sample", "q", DEV)[0]["build"] == prior
