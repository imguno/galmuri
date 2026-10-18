"""Admission, fairness and late-effect recovery across separate index lifecycles."""

from dataclasses import replace

import pytest
from duru import ReadOnlyLocalProvider

from galmuri import App, Principal
from galmuri.contracts.requests import RequestConflict
from galmuri.exposure.service import Service
from galmuri.retrieval import RetrievalConfig
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import DEV, Embedding, Store, fixture


def test_reindex_receipt_replays_after_restart_and_conflicts_with_changed_config(tmp_path):
    runtime, _, _, _ = fixture(tmp_path)
    runtime.sync()
    accepted = runtime.indexing.reindex("sample", request_id="client-request")
    runtime.drain()
    restarted = Runtime(runtime.database.path, list(runtime.apps.values()))
    assert restarted.indexing.reindex("sample", request_id="client-request") == accepted
    app = restarted.apps["sample"]
    changed = Runtime(
        runtime.database.path,
        [replace(app, retrieval=replace(app.retrieval, revision="next"))],
        activate=True,
    )
    before = changed.indexing.status()["jobs"]
    with pytest.raises(RequestConflict):
        changed.indexing.reindex("sample", request_id="client-request")
    assert changed.indexing.status()["jobs"] == before
    service = Service(changed)
    params = {"app": "sample", "request_id": "client-request"}
    assert service.call("reindex", params, Principal())["error"]["code"] == "forbidden"
    assert (
        service.call("reindex", params, Principal(administrator=True))["error"]["code"]
        == "conflict"
    )


def test_index_work_is_served_before_a_continuous_ingest_backlog_is_drained(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    for number in range(20):
        (files / f"{number:02}.md").write_text(f"document {number}", encoding="utf-8")
    app = App(
        "sample", ReadOnlyLocalProvider(files), retrieval=RetrievalConfig(Embedding(), Store())
    )
    runtime = Runtime(tmp_path / "state.sqlite", [app])
    runtime.collect("sample", force=True)
    assert runtime.work_once("worker")
    assert runtime.work_once("worker")
    status = runtime.status()
    assert sum(job["state"] == "READY" for job in status["jobs"]) == 19
    assert sum(job["state"] == "PUBLISHED" for job in status["indexing"]["jobs"]) == 1


def test_completed_cleanup_rechecks_ids_after_an_abandoned_late_upload(tmp_path):
    now = [100.0]
    runtime, source, embedding, store = fixture(tmp_path, clock=lambda: now[0])
    runtime.sync()
    old_points = tuple(store.points.values())
    old_ids = {point.id for point in old_points}
    source.version = "2"
    runtime.sync()
    assert not old_ids.intersection(store.points)
    current = runtime.search("sample", "query", DEV)[0]
    # An external operation can outlive its lease and the originating process.
    # No returning execution.finally is available to repair this write.
    store.upsert("test", old_points)
    assert old_ids <= store.points.keys()
    calls = embedding.calls
    now[0] += runtime.apps["sample"].retrieval.cleanup_interval
    assert runtime.indexing.work_once("cleanup")
    assert not old_ids.intersection(store.points)
    assert runtime.search("sample", "query", DEV)[0]["build"] == current["build"]
    assert embedding.calls == calls


def test_periodic_cleanup_progresses_while_index_builds_are_pending(tmp_path):
    now = [100.0]
    runtime, source, _, store = fixture(tmp_path, clock=lambda: now[0])
    runtime.sync()
    old_points = tuple(store.points.values())
    old_ids = {point.id for point in old_points}
    source.version = "2"
    runtime.sync()
    store.upsert("test", old_points)
    now[0] += runtime.apps["sample"].retrieval.cleanup_interval + 1
    # Recreate the worker, so fairness cannot depend on a previous process turn.
    fresh = Runtime(runtime.database.path, list(runtime.apps.values()), clock=lambda: now[0])
    fresh.indexing.reindex("sample")
    assert fresh.indexing.work_once("busy-worker")
    assert fresh.search("sample", "query", DEV)[0]["version"] == "2"
    fresh.indexing.reindex("sample")
    assert any(job["state"] == "READY" for job in fresh.indexing.status()["jobs"])
    assert fresh.indexing.work_once("busy-worker")
    assert not old_ids.intersection(store.points)
    assert any(job["state"] == "READY" for job in fresh.indexing.status()["jobs"])
    assert fresh.indexing.work_once("busy-worker")
    assert fresh.search("sample", "query", DEV)[0]["version"] == "2"
