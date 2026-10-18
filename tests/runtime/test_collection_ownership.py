import threading
from dataclasses import replace

from galmuri import Change, ChangeSet, FileRef
from galmuri.runtime import Runtime
from tests.runtime.test_lifecycle import make_runtime


def test_slow_discovery_can_commit_if_no_collector_reclaimed_it(tmp_path):
    now = [100]
    runtime, source = make_runtime(tmp_path, clock=lambda: now[0])

    def slow(checkpoint):
        now[0] += 50
        return ChangeSet((Change(FileRef("slow", "1")),), "done")

    source.changes = slow
    assert runtime.collect("drive")["enqueued"] == 1
    assert runtime.status()["apps"][0]["checkpoint"] == "done"


def test_reclaimed_collection_fences_the_previous_collectors_result(tmp_path):
    now = [100]
    runtime, source = make_runtime(tmp_path, clock=lambda: now[0])
    started, release = threading.Event(), threading.Event()
    calls = []

    def discover(checkpoint):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            return ChangeSet((Change(FileRef("old", "1")),), "old")
        return ChangeSet((Change(FileRef("new", "1")),), "new")

    source.changes = discover
    result = []
    thread = threading.Thread(target=lambda: result.append(runtime.collect("drive")))
    thread.start()
    assert started.wait(5)
    now[0] += 11
    assert runtime.collect("drive")["enqueued"] == 1
    release.set()
    thread.join(5)
    assert result[0]["state"] == "STALE"
    assert runtime.status()["apps"][0]["checkpoint"] == "new"
    assert [job["source_key"] for job in runtime.status()["jobs"]] == ["new"]


def test_scoped_sync_does_not_execute_another_apps_queued_jobs(tmp_path):
    runtime, source = make_runtime(tmp_path)
    called = []
    app_a = runtime.apps["drive"]
    app_b = replace(app_a, name="other", handler=lambda file: called.append(file))
    runtime = Runtime(runtime.database.path, [app_a, app_b], clock=lambda: 100)
    runtime.collect("other")
    runtime.sync("drive")
    assert called == []
    other_job = next(job for job in runtime.status()["jobs"] if job["app"] == "other")
    assert other_job["state"] == "READY"
