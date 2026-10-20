import io

from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.cli import CliAdapter
from galmuri.exposure.registry import AdapterRegistry, default_registry
from galmuri.exposure.service import Service

from .fakes import FakeRuntime


def test_capabilities_and_host_caller_are_authoritative():
    runtime = FakeRuntime()
    service = Service(runtime)
    caller = Principal("reader")
    assert "write" not in service.capabilities()["readonly"]["operations"]
    assert "write" in service.capabilities()["editable"]["operations"]
    rejected = service.call(
        "read",
        {
            "app": "readonly",
            "document_key": "private",
            "principal": {"administrator": True},
        },
        caller,
    )
    assert rejected["error"]["code"] == "invalid_request"
    assert service.call("status", {}, caller)["error"]["code"] == "forbidden"
    service.call("read", {"app": "readonly", "document_key": "guide"}, caller)
    assert runtime.last_principal is caller


def test_errors_and_cli_exit_status_do_not_disclose_raw_exception():
    service = Service(FakeRuntime())
    result = service.call("read", {"app": "readonly", "document_key": "explode"}, Principal())
    assert result["error"] == {
        "code": "internal_error",
        "message": "The operation could not be completed",
    }
    output = io.StringIO()
    assert CliAdapter(service).execute("status", {}, output=output) == 1
    assert '"forbidden"' in output.getvalue()


def test_worker_results_have_strict_boundary_contract():
    runtime = FakeRuntime()
    service = Service(runtime)
    admin = Principal("worker", administrator=True)
    claim = service.call("worker.claim", {"worker_id": "w1"}, admin)["result"]
    assert service.call("worker.claim", {"worker_id": "w1"}, Principal())["ok"] is False
    valid = {
        "claim": claim,
        "result": {
            "documents": [
                {
                    "key": "d1",
                    "text": "text",
                    "readers": ["group:dev"],
                    "writers": [],
                }
            ]
        },
    }
    assert service.call("worker.complete", valid, admin)["result"] is True
    assert runtime.completed.documents[0].readers == ("group:dev",)
    valid["result"]["documents"][0]["readers"] = "*"
    assert service.call("worker.complete", valid, admin)["error"]["code"] == "invalid_request"


def test_registry_allows_host_registered_adapter():
    class CustomAdapter:
        def __init__(self, service, **options):
            self.options = options

        def run(self):
            pass

    registry = AdapterRegistry()
    registry.register("custom", CustomAdapter)
    assert registry.create("custom", Service(FakeRuntime()), port=3).options == {"port": 3}
    assert default_registry().create("http", Service(FakeRuntime())).host == "127.0.0.1"


def test_authentication_never_infers_authority_from_unknown_token():
    import pytest

    from galmuri.exposure.service.errors import ExposureError

    auth = TokenAuthenticator({"host-secret": Principal("operator", administrator=True)})
    assert auth.authenticate("Bearer host-secret").administrator
    with pytest.raises(ExposureError):
        auth.authenticate("Bearer admin")


def test_reconciliation_requires_operator_and_exact_receipt():
    runtime = FakeRuntime()
    service = Service(runtime)
    admin = Principal("ops", administrator=True)
    request = {"job_id": "j1", "outcome": "retry_safe"}
    assert service.call("reconcile", request, Principal())["error"]["code"] == "forbidden"
    assert service.call("reconcile", request, admin)["ok"] is True
    assert runtime.reconciled == ("j1", "retry_safe")
    request["outcome"] = "succeeded"
    assert service.call("reconcile", request, admin)["error"]["code"] == "invalid_request"
    write = {"operation_id": "w1", "outcome": "applied"}
    assert service.call("reconcile_write", write, admin)["error"]["code"] == "invalid_request"
    write["ref"] = {"key": "source.md", "version": "v2", "metadata": {"format": "markdown"}}
    assert service.call("reconcile_write", write, admin)["ok"] is True
    assert runtime.reconciled_write[2].key == "source.md"
    write["outcome"] = "failed"
    assert service.call("reconcile_write", write, admin)["error"]["code"] == "invalid_request"


def test_worker_effect_unknown_is_preserved():
    from galmuri.contracts.files import EffectUnknown

    runtime = FakeRuntime()
    service = Service(runtime)
    admin = Principal("worker", administrator=True)
    params = {
        "claim": {"id": "j1", "token": "t1"},
        "error": "Connection lost",
        "kind": "effect_unknown",
    }
    assert service.call("worker.fail", params, admin)["ok"] is True
    assert isinstance(runtime.failure, EffectUnknown)
    params["kind"] = "arbitrary.module.Exception"
    assert service.call("worker.fail", params, admin)["error"]["code"] == "invalid_request"


def test_worker_claim_preserves_supported_app_revisions():
    runtime = FakeRuntime()
    service = Service(runtime)
    admin = Principal("worker", administrator=True)
    params = {"worker_id": "worker-1", "supported_apps": {"editable": "revision-3"}}
    assert service.call("worker.claim", params, admin)["ok"] is True
    assert runtime.supported_apps == {"editable": "revision-3"}
    params["supported_apps"] = {"editable": 3}
    assert service.call("worker.claim", params, admin)["error"]["code"] == "invalid_request"


def test_semantic_mode_and_maintenance_commands_cross_common_boundary():
    class Indexing:
        def status(self, app):
            return {"app": app, "jobs": []}

        def reindex(self, app):
            return {"app": app, "scheduled": 2}

        def retry(self, job_id):
            return job_id == "failed-build"

    class SemanticRuntime(FakeRuntime):
        indexing = Indexing()

        def search(self, app, query, principal, *, limit=20, mode=None):
            return {"mode": mode, "query": query, "limit": limit}

    service = Service(SemanticRuntime())
    reader = Principal("reader")
    operator = Principal("operator", administrator=True)
    params = {"app": "readonly", "query": "paraphrase", "mode": "vector", "limit": 3}
    assert service.call("search", params, reader)["result"] == {
        "mode": "vector",
        "query": "paraphrase",
        "limit": 3,
    }
    params["mode"] = "unknown"
    assert service.call("search", params, reader)["error"]["code"] == "invalid_request"
    for operation, arguments in (
        ("index_status", {"app": "readonly"}),
        ("reindex", {"app": "readonly"}),
        ("index_retry", {"job_id": "failed-build"}),
    ):
        assert service.call(operation, arguments, reader)["error"]["code"] == "forbidden"
        assert service.call(operation, arguments, operator)["ok"] is True
    assert Service(FakeRuntime()).call("index_status", {}, operator)["error"]["code"] == (
        "unsupported"
    )
