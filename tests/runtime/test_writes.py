import threading

import pytest

from galmuri import Change, ChangeSet, Document, FileRef, IngestResult, Principal
from galmuri.contracts.files import EffectUnknown, SourceConflict
from tests.runtime.test_lifecycle import make_runtime

DEV = Principal("alice", frozenset({"dev"}))


def test_source_write_queues_reindex_and_deduplicates_later_discovery(tmp_path):
    runtime, source = make_runtime(tmp_path)

    def write(key, content, expected_version):
        if source.version != expected_version:
            raise SourceConflict()
        source.content, source.version = content, "2"
        return FileRef(key, "2")

    source.write = write
    runtime.sync()
    result = runtime.write("drive", "doc", "updated", DEV, "1")
    assert result["indexing"] == "QUEUED"
    assert runtime.collect("drive", force=True)["enqueued"] == 0
    runtime.drain()
    assert runtime.read("drive", "doc", DEV)["text"] == "updated"
    with pytest.raises(SourceConflict):
        runtime.write("drive", "doc", "stale", DEV, "1")


def test_full_source_write_requires_all_derived_document_permissions(tmp_path):
    def split(file):
        return IngestResult(
            (
                Document("one", "one", writers=("group:dev",)),
                Document("two", "two", writers=("group:ops",)),
            )
        )

    runtime, source = make_runtime(tmp_path, split)
    calls = []
    source.write = lambda *args: calls.append(args)
    runtime.sync()
    with pytest.raises(PermissionError):
        runtime.write("drive", "one", "replace", DEV, "1")
    assert calls == []


def test_unknown_write_outcome_persists_and_blocks_blind_retry(tmp_path):
    runtime, source = make_runtime(tmp_path)
    calls = []

    def write(*args):
        calls.append(args)
        raise TimeoutError("response lost")

    source.write = write
    runtime.sync()
    with pytest.raises(EffectUnknown):
        runtime.write("drive", "doc", "replace", DEV, "1")
    operation = runtime.status()["writes"][0]
    assert operation["state"] == "RECONCILING"
    with pytest.raises(EffectUnknown):
        runtime.write("drive", "doc", "replace", DEV, "1")
    assert len(calls) == 1
    runtime.reconcile_write(operation["id"], "applied", FileRef("file", "2"))
    assert runtime.status()["writes"][0]["state"] == "SUCCEEDED"
    assert len(runtime.status()["jobs"]) == 2


def test_read_only_source_exposes_no_write_and_admin_cannot_bypass_acl(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.sync()
    admin = Principal("admin", administrator=True)
    assert "write" not in runtime.describe("drive", admin)["capabilities"]
    assert runtime.search("drive", "hello", admin) == []
    with pytest.raises(PermissionError):
        runtime.read("drive", "doc", admin)
    with pytest.raises(NotImplementedError):
        runtime.write("drive", "doc", "replace", admin, "1")


def test_slow_write_does_not_block_heartbeats_and_revocation_applies_to_new_intents(tmp_path):
    runtime, source = make_runtime(tmp_path)
    started, release, renewed = threading.Event(), threading.Event(), threading.Event()

    def slow_write(key, content, expected_version):
        started.set()
        assert release.wait(5)
        source.content, source.version = content, "3"
        return FileRef(key, "3")

    source.write = slow_write
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    claim = runtime.claim()
    outcomes = []
    writer = threading.Thread(
        target=lambda: outcomes.append(runtime.write("drive", "doc", "new", DEV, "2"))
    )
    writer.start()
    assert started.wait(5)

    def renew_and_revoke():
        assert runtime.heartbeat(claim)
        runtime.documents.set_permissions("drive", "doc", (), ())
        renewed.set()

    heartbeat = threading.Thread(target=renew_and_revoke)
    heartbeat.start()
    try:
        assert renewed.wait(2), "Source I/O must not hold the coordinator transaction"
    finally:
        release.set()
        writer.join(5)
        heartbeat.join(5)
    assert outcomes[0]["state"] == "SUCCEEDED"
    with pytest.raises(PermissionError):
        runtime.write("drive", "doc", "denied", DEV, "3")


def test_discovery_failure_never_advances_checkpoint(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.collect("drive")
    source.changes = lambda checkpoint: (_ for _ in ()).throw(ValueError("discovery failed"))
    with pytest.raises(ValueError):
        runtime.collect("drive", force=True)
    app = runtime.status()["apps"][0]
    assert app["checkpoint"] == "1"
    assert app["collection_state"] == "RETRY_WAIT"
    assert len(runtime.status()["jobs"]) == 1


def test_failed_batch_is_atomic_with_checkpoint(tmp_path):
    runtime, source = make_runtime(tmp_path)

    class BrokenChange:
        @property
        def ref(self):
            raise ValueError("bad ref")

    source.changes = lambda checkpoint: ChangeSet((Change(FileRef("a", "1")), BrokenChange()), "2")
    with pytest.raises(ValueError, match="bad ref"):
        runtime.collect("drive")
    assert runtime.status()["jobs"] == []
    assert runtime.status()["apps"][0]["checkpoint"] is None
