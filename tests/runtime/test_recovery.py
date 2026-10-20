import pytest

from tests.runtime.test_lifecycle import make_runtime


def test_confirmed_failures_obey_app_retry_budget(tmp_path):
    now = [100]

    def fails(file):
        raise ValueError("confirmed failure")

    runtime, _ = make_runtime(tmp_path, fails, lambda: now[0])
    runtime.collect("drive")
    for expected in ("RETRY_WAIT", "RETRY_WAIT", "FAILED"):
        assert runtime.work_once()
        assert runtime.status()["jobs"][0]["state"] == expected
        now[0] += 5
    assert not runtime.work_once()
    runtime.retry(runtime.status()["jobs"][0]["id"])
    assert runtime.status()["jobs"][0]["state"] == "READY"


def test_cancelled_pending_job_never_runs_and_cannot_retry(tmp_path):
    called = []
    runtime, _ = make_runtime(tmp_path, lambda file: called.append(file))
    runtime.collect("drive")
    job = runtime.status()["jobs"][0]
    runtime.cancel(job["id"])
    assert runtime.drain() == 0
    assert called == []
    with pytest.raises(ValueError, match="confirmed failures"):
        runtime.retry(job["id"])


def test_attempt_logs_survive_runtime_restart_and_do_not_expose_tokens(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.sync()
    from galmuri.runtime import Runtime

    restarted = Runtime(runtime.database.path, list(runtime.apps.values()), clock=lambda: 100)
    status = restarted.status()
    assert [event["state"] for event in reversed(status["events"])] == [
        "READY",
        "RUNNING",
        "SUCCEEDED",
    ]
    assert status["attempts"][0]["outcome"] == "SUCCEEDED"
    assert "token" not in status["jobs"][0]
    assert "token" not in status["attempts"][0]


def test_reconciliation_cannot_retry_an_old_source_intent(tmp_path):
    now = [100]
    runtime, source = make_runtime(tmp_path, clock=lambda: now[0])
    runtime.collect("drive")
    old = runtime.claim()
    now[0] += 11
    assert runtime.claim() is None
    source.version = "2"
    runtime.collect("drive", force=True)
    runtime.reconcile(old["id"], "retry_safe")
    old_job = next(job for job in runtime.status()["jobs"] if job["id"] == old["id"])
    assert old_job["state"] == "SUPERSEDED"
    assert runtime.work_once()
