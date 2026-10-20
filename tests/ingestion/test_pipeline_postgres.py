"""Real remote metadata DB checkpoints survive another Runtime taking over."""

import os
from uuid import uuid4

import pytest

from galmuri import App, Principal
from galmuri.collection.policies import SyncPolicy
from galmuri.execution.persistence.postgres import PostgresBackend
from galmuri.ingestion.stages.ownership import CheckpointRejected
from galmuri.runtime import Runtime
from tests.ingestion.test_checkpoints import Source
from tests.ingestion.test_pipeline_checkpoints import Stages, rows


@pytest.fixture
def remote():
    driver = pytest.importorskip("psycopg")
    dsn = os.environ.get("FRAMEWORK_POSTGRES_DSN")
    if not dsn:
        pytest.skip("FRAMEWORK_POSTGRES_DSN is not configured")
    schema = "test_pipeline_" + uuid4().hex
    yield dsn, schema
    with driver.connect(dsn, autocommit=True) as connection:
        connection.execute(
            driver.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(driver.sql.Identifier(schema))
        )


def test_postgres_restart_uses_accepted_steps_and_purges_terminal_payloads(tmp_path, remote):
    dsn, schema = remote
    source, stages = Source(), Stages()
    stages.fail = True
    initial = Runtime(
        tmp_path / "local.db",
        [
            App(
                "docs",
                source,
                process=stages.pipeline(),
                retrieval=None,
                policy=SyncPolicy(retry_delay=0),
            )
        ],
        backend=PostgresBackend(dsn, schema=schema),
        default_permissions={"read": ["group:team"], "write": []},
    )
    initial.sync()
    assert initial.status()["jobs"][0]["state"] == "FAILED"
    assert source.reads == stages.parses == 1
    assert stages.cleans == 3
    assert [row["name"] for row in rows(initial)] == ["decode"]

    stages.fail = False
    resumed = Runtime(
        tmp_path / "different-local.db",
        list(initial.apps.values()),
        backend=PostgresBackend(dsn, schema=schema),
    )
    resumed.retry(resumed.status()["jobs"][0]["id"])
    resumed.drain()
    assert source.reads == stages.parses == 1
    assert stages.cleans == 4
    with pytest.raises(PermissionError):
        resumed.read("docs", "doc", Principal())
    assert (
        resumed.read("docs", "doc", Principal("member", frozenset({"team"})))["text"]
        == "PRIVATE CONTENT"
    )
    assert rows(resumed) == []
    with resumed.database.connection() as connection:
        checkpoint = connection.execute("SELECT * FROM ingestion_checkpoints").fetchone()
        assert checkpoint["stage"] == "PUBLISHED"
        assert checkpoint["content"] is checkpoint["file_metadata"] is checkpoint["parsed"] is None


def test_postgres_new_runtime_fences_expired_step_claim_and_reuses_checkpoint(tmp_path, remote):
    dsn, schema = remote
    now = [100.0]
    source, stages = Source(), Stages()
    initial = Runtime(
        tmp_path / "local.db",
        [
            App(
                "docs",
                source,
                process=stages.pipeline(),
                retrieval=None,
                policy=SyncPolicy(retry_delay=0),
            )
        ],
        clock=lambda: now[0],
        backend=PostgresBackend(dsn, schema=schema),
    )
    initial.collect("docs")
    old_claim = initial.claim()
    stages.callback = lambda: now.__setitem__(0, now[0] + 31)
    with pytest.raises(CheckpointRejected):
        initial.ingestion.run(old_claim, initial.apps["docs"])
    assert [row["name"] for row in rows(initial)] == ["decode"]

    stages.callback = lambda: None
    replacement = Runtime(
        tmp_path / "different-local.db",
        list(initial.apps.values()),
        clock=lambda: now[0],
        backend=PostgresBackend(dsn, schema=schema),
    )
    assert replacement.claim() is None
    assert replacement.status()["jobs"][0]["state"] == "RECONCILING"
    replacement.reconcile(old_claim["id"], "retry_safe")
    new_claim = replacement.claim()
    assert new_claim["id"] == old_claim["id"]
    assert new_claim["token"] != old_claim["token"]
    with pytest.raises(CheckpointRejected):
        initial.ingestion.run(old_claim, initial.apps["docs"])
    result = replacement.ingestion.run(new_claim, replacement.apps["docs"])
    assert replacement.complete(new_claim, result)
    replacement.ingestion.release_completed()
    assert source.reads == stages.parses == 1
    assert stages.cleans == 2
    assert replacement.read("docs", "doc", Principal())
    assert rows(replacement) == []
