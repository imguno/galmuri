"""A failed or stale stage cannot erase earlier accepted processing boundaries."""

from dataclasses import replace

import pytest

from galmuri import App, Document, File, FileRef, IngestResult, Principal
from galmuri.collection.policies import SyncPolicy
from galmuri.ingestion.stages.ownership import CheckpointRejected
from galmuri.processing import Pipeline, Step
from galmuri.runtime import Runtime
from tests.ingestion.test_checkpoints import Source


class Stages:
    def __init__(self):
        self.parses = self.cleans = 0
        self.fail = False
        self.callback = lambda: None

    def parse(self, file):
        self.parses += 1
        return (Document("doc", file.text),)

    def clean(self, documents):
        self.cleans += 1
        self.callback()
        if self.fail:
            raise RuntimeError("clean unavailable")
        return tuple(replace(document, text=document.text.upper()) for document in documents)

    def pipeline(self, revision="1"):
        return Pipeline(
            Step("decode", self.parse, "file", "documents", "test-parse"),
            Step("normalize", self.clean, identity="test-clean", revision=revision),
        )


def fixture(tmp_path, *, clock=None, source=None, stages=None, permissions=None):
    source, stages = source or Source(), stages or Stages()
    runtime = Runtime(
        tmp_path / "state.db",
        [
            App(
                "docs",
                source,
                process=stages.pipeline(),
                retrieval=None,
                policy=SyncPolicy(retry_delay=0),
            )
        ],
        default_permissions=permissions,
        **({"clock": clock} if clock else {}),
    )
    return runtime, source, stages


def rows(runtime, job=None):
    with runtime.database.connection() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM ingestion_step_checkpoints" + (" WHERE job=?" if job else ""),
                (job,) if job else (),
            )
        ]


def test_retry_after_restart_reuses_accepted_file_and_prior_steps(tmp_path):
    runtime, source, stages = fixture(tmp_path)
    stages.fail = True
    runtime.sync()
    assert source.reads == stages.parses == 1
    assert stages.cleans == 3
    assert runtime.status()["ingestion"][0]["stage"] == "STEP:normalize"
    assert [row["name"] for row in rows(runtime)] == ["decode"]
    stages.fail = False
    fresh = Runtime(runtime.database.path, list(runtime.apps.values()))
    fresh.retry(fresh.status()["jobs"][0]["id"])
    fresh.drain()
    assert source.reads == stages.parses == 1
    assert stages.cleans == 4
    assert fresh.read("docs", "doc", Principal())["text"] == "PRIVATE CONTENT"
    assert fresh.status()["ingestion"][0]["stage"] == "PUBLISHED"
    assert rows(fresh) == []


def test_publication_retry_reuses_accepted_final_result(tmp_path, monkeypatch):
    runtime, source, stages = fixture(tmp_path)
    original = runtime.documents.publish

    def unavailable(job, result):
        raise RuntimeError("publication unavailable")

    monkeypatch.setattr(runtime.documents, "publish", unavailable)
    runtime.sync()
    assert source.reads == stages.parses == stages.cleans == 1
    assert [row["name"] for row in rows(runtime)] == ["decode", "normalize", "prepare"]
    monkeypatch.setattr(runtime.documents, "publish", original)
    runtime.retry(runtime.status()["jobs"][0]["id"])
    runtime.drain()
    assert source.reads == stages.parses == stages.cleans == 1
    assert rows(runtime) == []


@pytest.mark.parametrize("guard", ["lease", "source"])
def test_stale_external_callback_cannot_accept_stage_output(tmp_path, guard):
    now = [100.0]
    runtime, source, stages = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("docs")
    job = runtime.claim()

    def invalidate():
        if guard == "lease":
            now[0] += 31
        else:
            source.version = "2"
            runtime.collect("docs", force=True)

    stages.callback = invalidate
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job, runtime.apps["docs"])
    assert [row["name"] for row in rows(runtime)] == ["decode"]
    with pytest.raises(PermissionError):
        runtime.read("docs", "doc", Principal())


def test_current_acl_override_survives_pipeline_automatic_defaults(tmp_path):
    runtime, source, stages = fixture(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("docs", force=True)
    stages.callback = lambda: runtime.documents.set_permissions("docs", "doc", (), ())
    runtime.work_once()
    stages.callback = lambda: None
    runtime.drain()
    with pytest.raises(PermissionError):
        runtime.read("docs", "doc", Principal())


def test_pipeline_revision_activation_fences_accepted_steps(tmp_path):
    runtime, source, stages = fixture(tmp_path)
    runtime.collect("docs")
    job = runtime.claim()
    original = runtime.apps["docs"]
    result = runtime.ingestion.run(job, original)
    changed = replace(original, process=stages.pipeline(revision="2"))
    with pytest.raises(ValueError, match="activate"):
        Runtime(runtime.database.path, [changed])
    fresh = Runtime(runtime.database.path, [changed], activate=True)
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job, original)
    assert not runtime.complete(job, result)
    fresh.sync()
    assert fresh.read("docs", "doc", Principal())
    assert rows(fresh) == []


def test_reconciliation_keeps_private_snapshots_until_confirmed_cancel(tmp_path):
    now = [100.0]
    runtime, _, _ = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("docs")
    job = runtime.claim()
    runtime.ingestion.run(job, runtime.apps["docs"])
    now[0] += 31
    assert runtime.claim() is None
    runtime.ingestion.release_completed()
    assert len(rows(runtime)) == 3
    runtime.reconcile(job["id"], "cancelled")
    runtime.ingestion.release_completed()
    assert rows(runtime) == []


def test_explicit_result_permissions_are_not_replaced_by_global_defaults(tmp_path):
    def finish(file):
        return IngestResult((Document("private", file.text, readers=("user:alice",)),), ("done",))

    runtime = Runtime(
        tmp_path / "state.db",
        [
            App(
                "docs",
                Source(),
                process=Pipeline(Step("finish", finish, "file", "result")),
                retrieval=None,
            )
        ],
        default_permissions={"read": ("*",), "write": ("*",)},
    )
    runtime.sync()
    with pytest.raises(PermissionError):
        runtime.read("docs", "private", Principal())
    assert runtime.read("docs", "private", Principal("alice"))


def test_file_step_can_transform_content_but_cannot_accept_different_identity(tmp_path):
    def wrong(file):
        return File(FileRef("other", file.ref.version), file.content)

    def parse(file):
        return (Document("doc", file.text),)

    pipeline = Pipeline(
        Step("wrong", wrong, "file", "file"), Step("parse", parse, "file", "documents")
    )
    runtime = Runtime(
        tmp_path / "state.db",
        [App("docs", Source(), process=pipeline, retrieval=None, policy=SyncPolicy(retry_delay=0))],
    )
    runtime.sync()
    assert runtime.status()["jobs"][0]["state"] == "FAILED"
    assert rows(runtime) == []


def test_custom_policy_still_owns_execution(tmp_path):
    class Custom(SyncPolicy):
        def execute(self, source, ref, handler):
            raise RuntimeError("custom execution")

    stages = Stages()
    runtime = Runtime(
        tmp_path / "state.db",
        [
            App(
                "docs",
                Source(),
                process=stages.pipeline(),
                retrieval=None,
                policy=Custom(retry_delay=0),
            )
        ],
    )
    runtime.sync()
    assert runtime.status()["ingestion"] == []
    assert stages.parses == stages.cleans == 0
    assert "custom execution" in runtime.status()["jobs"][0]["error"]
