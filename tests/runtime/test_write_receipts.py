import pytest

from galmuri import Change, ChangeSet, FileRef
from galmuri.contracts.files import EffectUnknown
from tests.runtime.test_lifecycle import make_runtime
from tests.runtime.test_writes import DEV


def uncertain_write(runtime, source):
    def write(key, content, expected_version):
        source.version, source.content = "2", content
        raise TimeoutError("write applied but receipt lost")

    source.write = write
    runtime.sync()
    with pytest.raises(EffectUnknown):
        runtime.write("drive", "doc", "version two", DEV, "1")
    return runtime.status()["writes"][0]["id"]


def test_applied_reconciliation_preserves_newer_discovered_version_and_checkpoint(tmp_path):
    runtime, source = make_runtime(tmp_path)
    operation = uncertain_write(runtime, source)
    source.version, source.content = "3", b"version three"
    runtime.collect("drive", force=True)
    third = next(job for job in runtime.status()["jobs"] if job["version"] == "3")

    runtime.reconcile_write(operation, "applied", FileRef("file", "2"))

    status = runtime.status()
    assert status["writes"][0]["state"] == "SUCCEEDED"
    assert status["apps"][0]["checkpoint"] == "3"
    assert next(job for job in status["jobs"] if job["id"] == third["id"])["state"] == "READY"
    assert not any(job["version"] == "2" for job in status["jobs"])
    runtime.drain()
    assert runtime.read("drive", "doc", DEV)["text"] == "version three"
    assert runtime.collect("drive", force=True)["enqueued"] == 0


def test_applied_reconciliation_preserves_observed_deletion(tmp_path):
    runtime, source = make_runtime(tmp_path)
    operation = uncertain_write(runtime, source)
    source.changes = lambda checkpoint: ChangeSet(
        (Change(FileRef("file", "3"), deleted=True),), "3"
    )
    runtime.collect("drive", force=True)

    runtime.reconcile_write(operation, "applied", FileRef("file", "2"))

    status = runtime.status()
    assert status["writes"][0]["state"] == "SUCCEEDED"
    assert next(job for job in status["jobs"] if job["deleted"])["state"] == "READY"
    assert not any(job["version"] == "2" for job in status["jobs"])
    runtime.drain()
    assert runtime.search("drive", "", DEV) == []


def test_direct_write_receipt_uses_same_newer_intent_guard(tmp_path):
    runtime, source = make_runtime(tmp_path)

    def write(key, content, expected_version):
        source.version, source.content = "3", b"newer external update"
        runtime.collect("drive", force=True)
        return FileRef(key, "2")

    source.write = write
    runtime.sync()
    receipt = runtime.write("drive", "doc", "version two", DEV, "1")

    assert receipt["state"] == "SUCCEEDED"
    assert receipt["indexing"] == "SUPERSEDED"
    assert runtime.status()["writes"][0]["state"] == "SUCCEEDED"
    assert not any(job["version"] == "2" for job in runtime.status()["jobs"])
    runtime.drain()
    assert runtime.read("drive", "doc", DEV)["text"] == "newer external update"
