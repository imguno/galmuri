from dataclasses import replace

import pytest

from galmuri import App, FileRef, Principal
from galmuri.execution.persistence.backend import SQLiteBackend
from galmuri.runtime import Runtime
from tests.runtime.test_lifecycle import Policy, make_runtime, prepared


def test_new_revision_restarts_collection_and_supersedes_old_claim(tmp_path):
    runtime, source = make_runtime(tmp_path)
    runtime.sync()
    source.version = "2"
    runtime.collect("drive", force=True)
    claim = runtime.claim()
    replacement = Runtime(
        runtime.database.path,
        [App("drive", source, prepared, Policy(), revision="2")],
        clock=lambda: 100,
        activate=True,
    )
    assert replacement.status()["apps"][0]["checkpoint"] is None
    assert replacement.status()["apps"][0]["next_collection"] == 0
    assert not runtime.complete(claim, prepared(source.read(FileRef("file", "2"))))
    assert replacement.collect("drive")["enqueued"] == 1
    assert replacement.work_once()
    assert any(
        job["revision"] == "2" and job["state"] == "SUCCEEDED"
        for job in replacement.status()["jobs"]
    )
    assert (
        replacement.read("drive", "doc", Principal("alice", frozenset({"dev"})))["version"] == "2"
    )


def test_source_identity_switch_requires_explicit_revision(tmp_path):
    runtime, source = make_runtime(tmp_path)
    source.identity = "original"
    runtime = Runtime(tmp_path / "identity.db", list(runtime.apps.values()), clock=lambda: 100)
    runtime.sync()
    source.identity = "replacement"
    with pytest.raises(ValueError, match="identity changed"):
        Runtime(runtime.database.path, list(runtime.apps.values()))
    updated = Runtime(
        runtime.database.path,
        [replace(runtime.apps["drive"], revision="2")],
        clock=lambda: 100,
        activate=True,
    )
    assert updated.search("drive", "hello", Principal("alice", frozenset({"dev"}))) == []
    assert updated.collect("drive")["enqueued"] == 1


def test_runtime_uses_backend_contract_not_database_sql(tmp_path):
    class Replacement:
        def open(self, apps, clock, *, activate=False):
            components = SQLiteBackend(tmp_path / "actual.db").open(apps, clock, activate=activate)
            # Consumer-facing database deliberately has no connection/transaction methods.
            return replace(components, database=object())

    runtime, _ = make_runtime(tmp_path)
    replacement = Runtime(
        tmp_path / "unused.db",
        list(runtime.apps.values()),
        clock=lambda: 100,
        backend=Replacement(),
    )
    replacement.sync()
    replacement.pause("drive")
    replacement.resume("drive")
    assert replacement.read("drive", "doc", Principal("alice", frozenset({"dev"})))["text"]
    assert replacement.status()["jobs"][0]["state"] == "SUCCEEDED"


def test_remote_claim_only_takes_supported_app_revision(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.collect("drive")
    assert runtime.claim("old-worker", {"drive": "old"}) is None
    assert runtime.claim("other-worker", {"other": "1"}) is None
    assert runtime.status()["jobs"][0]["attempts"] == 0
    assert runtime.claim("valid-worker", {"drive": "1"})["app"] == "drive"


def test_live_old_coordinator_cannot_consume_current_revision_jobs(tmp_path):
    old, source = make_runtime(tmp_path)
    current = Runtime(
        old.database.path,
        [replace(old.apps["drive"], revision="2")],
        clock=lambda: 100,
        activate=True,
    )
    current.collect("drive")
    assert old.work_once() is False
    assert current.status()["jobs"][0]["state"] == "READY"
    assert current.work_once()
    assert current.status()["jobs"][0]["state"] == "SUCCEEDED"


def test_constructor_cannot_implicitly_replace_active_revision(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    revised = replace(runtime.apps["drive"], revision="2")
    with pytest.raises(ValueError, match="explicit activate"):
        Runtime(runtime.database.path, [revised])
    current = Runtime(runtime.database.path, [revised], activate=True)
    with pytest.raises(ValueError, match="explicit activate"):
        Runtime(runtime.database.path, list(runtime.apps.values()))
    assert current.status()["apps"][0]["revision"] == "2"
