"""Separate app databases preserve ownership, visibility and recovery contracts."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from galmuri import App, Principal
from galmuri.contracts.files import EffectUnknown
from galmuri.execution.persistence.backend import SQLiteBackend
from galmuri.execution.routing import RoutedBackend
from galmuri.retrieval import RetrievalConfig
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import Embedding, Store
from tests.runtime.test_lifecycle import Policy, Source, prepared

DEV = Principal("alice", frozenset({"dev"}))


def routed(tmp_path, *, shared=False, semantic=False):
    sources = {name: Source() for name in ("alpha", "beta")}
    backends = {name: SQLiteBackend(tmp_path / (name + ".sqlite")) for name in sources}
    if shared is True:
        backends["beta"] = backends["alpha"]
    elif shared in {"physical", "aliases"}:
        backends["beta"] = SQLiteBackend(tmp_path / "alpha.sqlite")
        if shared == "aliases":
            # Distinct DNS/connection aliases can resolve to one physical target.
            backends = {
                name: SimpleNamespace(identity=name, open=backend.open)
                for name, backend in backends.items()
            }
    apps = []
    for name, source in sources.items():
        source.content = (name + " content").encode()
        app = App(name, source, prepared, Policy())
        if semantic:
            app = replace(app, retrieval=RetrievalConfig(Embedding(), Store(), retry_delay=0))
        apps.append(app)
    backend = RoutedBackend(backends)
    runtime = Runtime(tmp_path / "unused.sqlite", apps, clock=lambda: 100, backend=backend)
    return runtime, sources, backend


@pytest.mark.parametrize("shared", [False, True, "physical", "aliases"])
def test_routed_publication_queries_and_aggregate_status_do_not_cross_apps(tmp_path, shared):
    runtime, _, _ = routed(tmp_path, shared=shared)
    assert runtime.sync()["processed"] == 2
    assert runtime.read("alpha", "doc", DEV)["text"] == "alpha content"
    assert runtime.read("beta", "doc", DEV)["text"] == "beta content"
    assert runtime.search("alpha", "beta", DEV) == []
    assert runtime.search("beta", "content", Principal()) == []
    status = runtime.status()
    assert {row["name"] for row in status["apps"]} == {"alpha", "beta"}
    assert len(status["jobs"]) == len(status["attempts"]) == 2
    assert [row["app"] for row in runtime.status("beta")["jobs"]] == ["beta"]
    runtime.documents.set_permissions("beta", "doc", (), ())
    assert runtime.read("alpha", "doc", DEV)["text"] == "alpha content"
    with pytest.raises(PermissionError):
        runtime.read("beta", "doc", DEV)
    runtime.pause("alpha")
    assert runtime.status("alpha")["apps"][0]["paused"]
    assert not runtime.status("beta")["apps"][0]["paused"]


def test_routed_claim_uses_real_token_owner_and_commands_find_persistent_job(tmp_path):
    runtime, _, _ = routed(tmp_path)
    runtime.collect("alpha")
    runtime.collect("beta")
    first, second = runtime.claim("worker"), runtime.claim("worker")
    assert [first["app"], second["app"]] == ["alpha", "beta"]
    assert runtime.heartbeat(first)
    assert not runtime.heartbeat(first | {"token": "stale"})
    assert runtime._owned(first | {"app": "beta"})["app"] == "alpha"
    runtime.fail(first, RuntimeError("transient"))
    runtime.retry(first["id"])
    runtime.cancel(first["id"])
    assert runtime.status("alpha")["jobs"][0]["state"] == "CANCELLED"
    assert runtime.status("beta")["jobs"][0]["state"] == "RUNNING"
    runtime.fail(second, EffectUnknown("unknown source effect"))
    runtime.reconcile(second["id"], "cancelled")
    assert runtime.status("beta")["jobs"][0]["state"] == "CANCELLED"
    with pytest.raises(KeyError):
        runtime.retry("missing")


def test_routed_source_write_reconciliation_finds_owner_without_crossing_apps(tmp_path):
    runtime, sources, _ = routed(tmp_path)

    def uncertain(*args):
        raise TimeoutError("source response lost")

    sources["beta"].write = uncertain
    runtime.sync()
    with pytest.raises(EffectUnknown):
        runtime.write("beta", "doc", "changed", DEV, "1")
    operation = runtime.status("beta")["writes"][0]
    runtime.reconcile_write(operation["id"], "not_applied")
    assert runtime.status("beta")["writes"][0]["state"] == "FAILED"
    assert runtime.status("alpha")["writes"] == []
    assert runtime.read("alpha", "doc", DEV)["text"] == "alpha content"


def test_routed_indexing_rebuild_and_failed_job_retry_stay_in_selected_app(tmp_path):
    runtime, _, _ = routed(tmp_path, semantic=True)
    runtime.sync()
    assert runtime.search("alpha", "semantic synonym", DEV)[0]["text"] == "alpha content"
    rebuilt = runtime.indexing.reindex("beta")
    assert rebuilt["scheduled"] == 1
    assert len(runtime.indexing.status("alpha")["jobs"]) == 1
    runtime.apps["beta"].retrieval.store.fail = True
    runtime.drain(app_name="beta")
    failed = next(
        job for job in runtime.indexing.status("beta")["jobs"] if job["state"] == "FAILED"
    )
    runtime.apps["beta"].retrieval.store.fail = False
    runtime.indexing.retry(failed["id"])
    runtime.drain(app_name="beta")
    jobs = runtime.indexing.status()["jobs"]
    assert sum(job["state"] == "PUBLISHED" for job in jobs) == 2
    assert runtime.read("alpha", "doc", DEV)["version"] == "1"


def test_routed_supported_app_claims_never_pick_another_database(tmp_path):
    runtime, _, _ = routed(tmp_path)
    runtime.collect("alpha")
    runtime.collect("beta")
    assert runtime.claim("beta-worker", {"beta": runtime.apps["beta"].revision})["app"] == "beta"
    assert runtime.claim("beta-worker", {"beta": runtime.apps["beta"].revision}) is None
    assert runtime.claim("alpha-worker")["app"] == "alpha"


def test_routed_unknown_backend_app_fails_before_opening_databases(tmp_path):
    app = App("alpha", Source(), prepared, Policy())
    with pytest.raises(KeyError):
        RoutedBackend({}).open({"alpha": app}, lambda: 100)
    assert not (tmp_path / "unused.sqlite").exists()


def test_routed_default_ingestion_checkpoints_release_in_owning_database(tmp_path):
    apps = [App(name, Source(), retrieval=None) for name in ("alpha", "beta")]
    backend = RoutedBackend(
        {app.name: SQLiteBackend(tmp_path / (app.name + ".sqlite")) for app in apps}
    )
    runtime = Runtime(tmp_path / "unused.sqlite", apps, backend=backend)
    assert runtime.sync()["processed"] == 2
    checkpoints = runtime.status()["ingestion"]
    assert {row["app"] for row in checkpoints} == {"alpha", "beta"}
    assert all(row["stage"] == "PUBLISHED" for row in checkpoints)
    for app in apps:
        assert [row["app"] for row in runtime.status(app.name)["ingestion"]] == [app.name]
        assert runtime.search(app.name, "hello", Principal())
