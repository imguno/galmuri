from types import SimpleNamespace

from galmuri.workers.remote import HttpWorker


def worker_with_claim(claim, app):
    worker = HttpWorker("http://localhost", "token", {"sample": app}, "test")
    calls = []

    def call(operation, params):
        calls.append((operation, params))
        return claim if operation == "worker.claim" else True

    worker.call = call
    return worker, calls


def make_app():
    def execute(*args):
        raise AssertionError("Deleted or incompatible input must never execute handler")

    return SimpleNamespace(
        revision="1",
        source=object(),
        handler=object(),
        policy=SimpleNamespace(lease_seconds=30, execute=execute),
    )


def test_remote_deletion_publishes_empty_result_without_reading_missing_file():
    worker, calls = worker_with_claim(
        {
            "app": "sample",
            "revision": "1",
            "deleted": True,
            "id": "job",
            "token": "fence",
        },
        make_app(),
    )
    assert worker.run_once()
    result = next(params["result"] for op, params in calls if op == "worker.complete")
    assert result == {"documents": (), "messages": ()}
    assert not any(op == "worker.fail" for op, _ in calls)


def test_remote_skips_superseded_claim_without_starting_handler():
    worker, calls = worker_with_claim({"skip": True}, make_app())
    assert worker.run_once()
    assert len(calls) == 1


def test_remote_checks_handler_revision_before_executing():
    worker, calls = worker_with_claim(
        {
            "app": "sample",
            "revision": "2",
            "deleted": False,
            "id": "job",
            "token": "fence",
        },
        make_app(),
    )
    assert worker.run_once()
    assert calls[0][1]["supported_apps"] == {"sample": "1"}
    assert any(op == "worker.fail" for op, _ in calls)
    assert not any(op == "worker.complete" for op, _ in calls)
