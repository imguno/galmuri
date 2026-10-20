from concurrent.futures import ThreadPoolExecutor

import pytest

from galmuri import Change, ChangeSet, Document, FileRef, IngestResult, Principal
from galmuri.runtime import Runtime
from tests.runtime.test_lifecycle import make_runtime, prepared


def test_two_coordinators_claim_once(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.collect("drive")
    other = Runtime(runtime.database.path, list(runtime.apps.values()), clock=lambda: 100)
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda item: item.claim("worker"), [runtime, other]))
    assert sum(claim is not None for claim in claims) == 1


def test_scheduler_only_discovers_and_never_processes(tmp_path):
    calls = []
    runtime, _ = make_runtime(tmp_path, lambda file: calls.append(file))
    result = runtime.tick()
    assert result["collections"]["drive"]["enqueued"] == 1
    assert calls == []
    assert runtime.status()["jobs"][0]["state"] == "READY"


def test_expired_claim_requires_reconciliation_and_rejects_late_result(tmp_path):
    now = [100]
    runtime, source = make_runtime(tmp_path, clock=lambda: now[0])
    runtime.collect("drive")
    claim = runtime.claim()
    now[0] += 11
    assert runtime.claim() is None
    assert not runtime.complete(claim, prepared(source.read(FileRef("file", "1"))))
    job = runtime.status()["jobs"][0]
    assert job["state"] == "RECONCILING"
    runtime.reconcile(claim["id"], "retry_safe")
    assert runtime.work_once()
    assert runtime.status()["jobs"][0]["state"] == "SUCCEEDED"


def test_new_version_fences_old_claim(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.collect("drive")
    old = runtime.claim()
    source.version = "2"
    source.content = b"latest"
    runtime.collect("drive", force=True)
    assert not runtime.complete(old, IngestResult((Document("doc", "old", readers=("*",)),)))
    runtime.drain()
    assert runtime.read("drive", "doc", Principal("dev", frozenset({"dev"})))["text"] == "latest"


def test_remote_cannot_forge_acl_baseline_or_source_identity(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    claim = runtime.claim()
    runtime.documents.set_permissions("drive", "doc", (), ())
    claim["acl_generation"] = 1
    claim["source_key"] = "another-file"
    assert runtime.complete(claim, prepared(source.read(FileRef("file", "2"))))
    assert runtime.search("drive", "hello", Principal("dev", frozenset({"dev"}))) == []


def test_deletion_withdraws_before_cleanup_and_fences_late_work(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    old = runtime.claim()
    source.changes = lambda checkpoint: ChangeSet(
        (Change(FileRef("file", "3"), deleted=True),), "3"
    )
    runtime.collect("drive", force=True)
    assert runtime.search("drive", "hello", Principal("dev", frozenset({"dev"}))) == []
    assert not runtime.complete(old, prepared(source.read(FileRef("file", "2"))))
    runtime.drain()
    assert runtime.status()["documents"] == [{"app": "drive", "state": "DELETED", "count": 1}]


def test_pause_stops_new_claims_and_resume_restores_them(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.collect("drive")
    runtime.pause("drive")
    assert not runtime.work_once()
    assert runtime.collect("drive", force=True)["state"] == "PAUSED"
    runtime.resume("drive")
    assert runtime.work_once()


def test_running_cancel_does_not_assert_external_effect_was_undone(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.collect("drive")
    claim = runtime.claim()
    runtime.cancel(claim["id"])
    assert not runtime.complete(claim, prepared(source.read(FileRef("file", "1"))))
    assert runtime.status()["jobs"][0]["state"] == "RECONCILING"
    runtime.reconcile(claim["id"], "cancelled")
    assert runtime.status()["jobs"][0]["state"] == "CANCELLED"


def test_identity_collision_does_not_overwrite_another_file(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.sync()
    app = runtime.apps["drive"]
    app.source.changes = lambda checkpoint: ChangeSet((Change(FileRef("other", "1")),), "other")
    runtime.collect("drive", force=True)
    runtime.work_once()
    dev = Principal("dev", frozenset({"dev"}))
    assert runtime.read("drive", "doc", dev)["source_key"] == "file"
    assert any("already belongs" in (job["error"] or "") for job in runtime.status()["jobs"])


def test_versioned_source_is_checked_before_publication(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.collect("drive")
    claim = runtime.claim()
    source.current = lambda key: FileRef(key, "2")
    assert not runtime.complete(claim, prepared(source.read(FileRef("file", "1"))))
    assert runtime.search("drive", "hello", Principal()) == []


def test_permission_generation_has_compare_and_swap(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.sync()
    assert runtime.documents.set_permissions("drive", "doc", (), (), expected_revision=0) == 1
    with pytest.raises(ValueError, match="generation conflict"):
        runtime.documents.set_permissions("drive", "doc", ("*",), (), expected_revision=0)


def test_stale_acl_result_cannot_publish_a_new_public_document(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    claim = runtime.claim()
    runtime.documents.set_permissions("drive", "doc", (), ())
    assert runtime.complete(
        claim, IngestResult((Document("new-doc", "new content", readers=("*",)),))
    )
    assert runtime.search("drive", "new", Principal()) == []
