from galmuri import App, Change, ChangeSet, Document, File, FileRef, Principal, Processed
from galmuri.contracts.files import EffectUnknown
from galmuri.runtime import Runtime


class Source:
    def __init__(self):
        self.version = "1"
        self.content = b"hello world"

    def changes(self, checkpoint):
        return ChangeSet((Change(FileRef("file", self.version)),), self.version)

    def read(self, ref):
        return File(ref, self.content)


class Policy:
    interval = 60
    max_attempts = 3
    retry_delay = 5
    lease_seconds = 10

    def validate(self, source):
        pass

    def discover(self, source, checkpoint):
        return source.changes(checkpoint)

    def execute(self, source, ref, handler):
        return handler(source.read(ref))


def prepared(file):
    return Processed((Document("doc", file.text, readers=("group:dev",), writers=("group:dev",)),))


def make_runtime(tmp_path, handler=prepared, clock=lambda: 100):
    source = Source()
    runtime = Runtime(tmp_path / "state.db", [App("drive", source, handler, Policy())], clock)
    return runtime, source


def test_durable_discovery_and_acl(tmp_path):
    runtime, source = make_runtime(tmp_path)
    assert runtime.collect("drive")["enqueued"] == 1
    assert runtime.collect("drive", force=True)["enqueued"] == 0
    restarted = Runtime(runtime.database.path, list(runtime.apps.values()))
    assert restarted.drain() == 1
    assert runtime.search("drive", "hello", Principal()) == []
    dev = Principal("alice", frozenset({"dev"}))
    assert runtime.read("drive", "doc", dev)["text"] == "hello world"


def test_retry_delay_and_attempt_history(tmp_path):
    now = [100]
    calls = []

    def flaky(file):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("temporary")
        return prepared(file)

    runtime, _ = make_runtime(tmp_path, flaky, lambda: now[0])
    runtime.collect("drive")
    assert runtime.work_once()
    assert not runtime.work_once()
    now[0] += 5
    assert runtime.work_once()
    job = runtime.status()["jobs"][0]
    assert job["state"] == "SUCCEEDED"
    assert len(runtime.status()["attempts"]) == 2


def test_revoke_during_processing_never_regrants(tmp_path):
    revocations = []

    def revoke(file):
        if file.ref.version == "2":
            runtime.documents.set_permissions("drive", "doc", (), ())
            revocations.append(file.ref.version)
        return prepared(file)

    runtime, source = make_runtime(tmp_path, revoke)
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    runtime.drain()
    assert revocations == ["2"]
    assert runtime.search("drive", "hello", Principal("alice", frozenset({"dev"}))) == []


def test_unknown_effect_requires_reconciliation(tmp_path):
    def unknown(file):
        raise EffectUnknown("external outcome unknown")

    runtime, _ = make_runtime(tmp_path, unknown)
    runtime.sync()
    job = runtime.status()["jobs"][0]
    assert job["state"] == "RECONCILING"
    assert runtime.drain() == 0
    runtime.reconcile(job["id"], "retry_safe")
    assert runtime.status()["jobs"][0]["state"] == "RETRY_WAIT"
