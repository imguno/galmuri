"""Accepted boundaries survive retry; stale claim results cannot enter checkpoints."""

from dataclasses import replace

import pytest

from galmuri import App, Change, ChangeSet, Document, File, FileRef, Principal
from galmuri.collection.policies import SyncPolicy
from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.handler import IngestHandler
from galmuri.ingestion.stages.ownership import CheckpointRejected
from galmuri.parsing import ParsingConfig
from galmuri.runtime import Runtime


class Source:
    identity = "checkpoint-source"

    def __init__(self):
        self.version = "1"
        self.reads = 0
        self.on_read = lambda: None

    def changes(self, checkpoint):
        return ChangeSet((Change(FileRef("file", self.version)),), self.version)

    def read(self, ref):
        self.reads += 1
        self.on_read()
        return File(ref, b"private content")


class Parser:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.on_parse = lambda: None

    def __call__(self, file):
        self.calls += 1
        self.on_parse()
        if self.fail:
            raise ValueError("parser unavailable")
        return (Document("doc", file.text),)


def fixture(tmp_path, clock=None):
    source, parser = Source(), Parser()
    runtime = Runtime(
        tmp_path / "state.db",
        [
            App(
                "sample",
                source,
                parser=ParsingConfig(parser, identity="test-parser"),
                ingestion=IngestConfig(readers=("*",)),
                policy=SyncPolicy(retry_delay=0),
                retrieval=None,
            )
        ],
        **({"clock": clock} if clock else {}),
    )
    return runtime, source, parser


def test_parser_retry_uses_accepted_source_bytes(tmp_path):
    runtime, source, parser = fixture(tmp_path)
    parser.fail = True
    runtime.sync()
    assert source.reads == 1
    assert parser.calls == 3
    assert runtime.status()["ingestion"][0]["stage"] == "PARSING"
    assert runtime.status()["ingestion"][0]["error"] == "parser unavailable"
    parser.fail = False
    runtime.retry(runtime.status()["jobs"][0]["id"])
    runtime.drain()
    assert source.reads == 1
    assert runtime.read("sample", "doc", Principal())["text"] == "private content"


def test_preparation_retry_does_not_parse_or_read_again(tmp_path, monkeypatch):
    runtime, source, parser = fixture(tmp_path)
    original = IngestHandler.prepare
    attempts = []

    def unavailable(self, documents):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("preparation unavailable")
        return original(self, documents)

    monkeypatch.setattr(IngestHandler, "prepare", unavailable)
    runtime.sync()
    assert len(attempts) == 2
    assert source.reads == parser.calls == 1
    assert runtime.status()["ingestion"][0]["stage"] == "PUBLISHED"
    with runtime.database.connection() as connection:
        checkpoint = connection.execute("SELECT * FROM ingestion_checkpoints").fetchone()
        assert checkpoint["content"] is None and checkpoint["parsed"] is None


def test_publication_failure_reuses_parsed_snapshot_after_restart(tmp_path, monkeypatch):
    runtime, source, parser = fixture(tmp_path)
    original = runtime.documents.publish

    def unavailable(job, result):
        raise RuntimeError("publication unavailable")

    monkeypatch.setattr(runtime.documents, "publish", unavailable)
    runtime.sync()
    assert source.reads == parser.calls == 1
    assert runtime.status()["jobs"][0]["state"] == "FAILED"
    monkeypatch.setattr(runtime.documents, "publish", original)
    fresh = Runtime(runtime.database.path, list(runtime.apps.values()))
    fresh.retry(fresh.status()["jobs"][0]["id"])
    fresh.drain()
    assert source.reads == parser.calls == 1
    assert fresh.read("sample", "doc", Principal())


def test_source_changed_during_read_cannot_accept_bytes(tmp_path):
    runtime, source, parser = fixture(tmp_path)
    runtime.collect("sample")
    job = runtime.claim()

    def changed():
        source.version = "2"
        runtime.collect("sample", force=True)

    source.on_read = changed
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job, runtime.apps["sample"])
    with runtime.database.connection() as connection:
        assert connection.execute("SELECT content FROM ingestion_checkpoints").fetchone()[0] is None
    assert parser.calls == 0


def test_expired_lease_and_wrong_token_cannot_reuse_accepted_body(tmp_path):
    now = [100.0]
    runtime, source, parser = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("sample")
    job = runtime.claim()
    runtime.ingestion.run(job, runtime.apps["sample"])
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job | {"token": "forged"}, runtime.apps["sample"])
    now[0] += 31
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job, runtime.apps["sample"])
    assert source.reads == parser.calls == 1


def test_acl_change_during_parsing_rejects_stage_then_preserves_override(tmp_path):
    runtime, source, parser = fixture(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("sample", force=True)
    parser.on_parse = lambda: runtime.documents.set_permissions("sample", "doc", (), ())
    runtime.work_once()
    parser.on_parse = lambda: None
    runtime.drain()
    with pytest.raises(PermissionError):
        runtime.read("sample", "doc", Principal())
    assert source.reads == 2
    assert parser.calls == 3


def test_custom_workflow_execute_is_not_bypassed(tmp_path):
    runtime, source, parser = fixture(tmp_path)

    class Custom(SyncPolicy):
        def execute(self, source, ref, handler):
            raise ValueError("custom workflow still owns execution")

    custom = replace(runtime.apps["sample"], policy=Custom(retry_delay=0))
    runtime = Runtime(runtime.database.path, [custom])
    runtime.sync()
    assert runtime.status()["ingestion"] == []
    assert "custom workflow" in runtime.status()["jobs"][0]["error"]
    assert source.reads == parser.calls == 0


def test_read_failure_retries_read_without_invoking_parser(tmp_path):
    runtime, source, parser = fixture(tmp_path)

    def unavailable():
        raise RuntimeError("source unavailable")

    source.on_read = unavailable
    runtime.sync()
    assert source.reads == 3
    assert parser.calls == 0
    checkpoint = runtime.status()["ingestion"][0]
    assert checkpoint["stage"] == "READING"
    assert "content" not in checkpoint and "parsed" not in checkpoint
    source.on_read = lambda: None
    runtime.retry(runtime.status()["jobs"][0]["id"])
    runtime.drain()
    assert source.reads == 4
    assert parser.calls == 1


def test_parser_activation_fences_old_checkpoint_and_worker(tmp_path):
    runtime, source, parser = fixture(tmp_path)
    runtime.collect("sample")
    job = runtime.claim()
    runtime.ingestion.run(job, runtime.apps["sample"])
    original = runtime.apps["sample"]
    updated = replace(original, parser=replace(original.parser, revision="2"))
    with pytest.raises(ValueError, match="activate"):
        Runtime(runtime.database.path, [updated])
    replacement = Runtime(runtime.database.path, [updated], activate=True)
    with pytest.raises(CheckpointRejected):
        runtime.ingestion.run(job, original)
    assert not runtime.complete(job, original.handler(source.read(FileRef("file", "1"))))
    replacement.sync()
    assert replacement.read("sample", "doc", Principal())


def test_reconciliation_retains_checkpoint_until_confirmed_cancellation(tmp_path):
    now = [100.0]
    runtime, _, _ = fixture(tmp_path, clock=lambda: now[0])
    runtime.collect("sample")
    job = runtime.claim()
    runtime.ingestion.run(job, runtime.apps["sample"])
    now[0] += 31
    assert runtime.claim() is None
    runtime.ingestion.release_completed()
    with runtime.database.connection() as connection:
        checkpoint = connection.execute("SELECT * FROM ingestion_checkpoints").fetchone()
        assert checkpoint["content"] is not None and checkpoint["parsed"] is not None
    runtime.reconcile(job["id"], "cancelled")
    runtime.ingestion.release_completed()
    with runtime.database.connection() as connection:
        checkpoint = connection.execute("SELECT * FROM ingestion_checkpoints").fetchone()
        assert checkpoint["content"] is None and checkpoint["parsed"] is None
        assert checkpoint["stage"] == "CANCELLED"
