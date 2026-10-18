"""Real PostgreSQL operation, concurrency and exact-vector contracts.

Set FRAMEWORK_POSTGRES_DSN for an isolated disposable PostgreSQL service.
Every test creates and drops only its own randomly named schema.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from galmuri.retrieval import VectorPoint, VectorValidationError
from galmuri.retrieval.stores.postgres import PostgresVectorStore
from galmuri.storage.postgres import PostgresDatabase


@pytest.fixture
def database():
    driver = pytest.importorskip("psycopg")
    dsn = os.environ.get("FRAMEWORK_POSTGRES_DSN")
    if not dsn:
        pytest.skip("FRAMEWORK_POSTGRES_DSN is not configured")
    schema = "test_storage_" + uuid4().hex
    database = PostgresDatabase(dsn, schema=schema)
    yield database
    with driver.connect(dsn, autocommit=True) as connection:
        connection.execute('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')


def test_remote_schema_rows_bytes_flags_clock_and_rollback(database):
    database.initialize(
        "CREATE TABLE sample(id INTEGER PRIMARY KEY AUTOINCREMENT, value BYTEA, flag INTEGER);"
    )
    with database.transaction() as connection:
        connection.execute("INSERT INTO sample(value,flag) VALUES (?,?)", (b"hello", True))
        assert database.columns(connection, "sample") == {"id", "value", "flag"}
        timestamp = database.now()
        server = connection.execute("SELECT EXTRACT(EPOCH FROM clock_timestamp())").fetchone()[0]
        assert abs(timestamp - float(server)) < 1
    with database.connection() as connection:
        row = connection.execute("SELECT * FROM sample").fetchone()
        assert dict(row) == {"id": 1, "value": b"hello", "flag": 1}
        with pytest.raises(Exception, match="read-only"):
            connection.execute("UPDATE sample SET flag=0")
    with pytest.raises(RuntimeError, match="abort"):
        with database.transaction() as connection:
            connection.execute("UPDATE sample SET flag=0")
            raise RuntimeError("abort")
    with database.connection() as connection:
        assert connection.execute("SELECT flag FROM sample").fetchone()[0] == 1


def test_read_snapshot_is_stable_across_concurrent_commit(database):
    database.initialize("CREATE TABLE sample(value INTEGER)")
    with database.transaction() as connection:
        connection.execute("INSERT INTO sample VALUES (1)")
    with database.snapshot() as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == 1
        with database.transaction() as other:
            other.execute("UPDATE sample SET value=2")
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == 1


def test_concurrent_startup_and_serialized_read_modify_write(database):
    barrier = threading.Barrier(4)

    def increment(_):
        # Independent backend objects model process-owned connections.
        other = PostgresDatabase(database._dsn, schema=database.schema)
        barrier.wait(timeout=10)
        other.initialize("CREATE TABLE IF NOT EXISTS sample(id INTEGER PRIMARY KEY,value INTEGER)")
        for _ in range(8):
            with other.transaction() as connection:
                connection.execute("INSERT INTO sample VALUES (1,0) ON CONFLICT DO NOTHING")
                value = connection.execute("SELECT value FROM sample WHERE id=1").fetchone()[0]
                connection.execute("UPDATE sample SET value=? WHERE id=1", (value + 1,))

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(increment, range(4)))
    with database.connection() as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == 32


def test_schema_writer_lock_wait_is_bounded(database):
    driver = pytest.importorskip("psycopg")
    database.initialize("CREATE TABLE sample(value INTEGER)")
    contender = PostgresDatabase(database._dsn, schema=database.schema, lock_timeout=0.05)
    with database.transaction():
        with pytest.raises(driver.errors.LockNotAvailable):
            with contender.transaction():
                pytest.fail("Concurrent writer entered the held schema lock")


def test_advisory_lock_key_ignores_endpoint_and_credential_aliases(database):
    alias = PostgresDatabase("host=elsewhere dbname=other user=alias", schema=database.schema)
    assert alias.identity != database.identity
    assert alias._lock == database._lock


def test_statement_execution_is_bounded(database):
    driver = pytest.importorskip("psycopg")
    bounded = PostgresDatabase(database._dsn, schema=database.schema, statement_timeout=0.05)
    with pytest.raises(driver.errors.QueryCanceled):
        with bounded.connection() as connection:
            connection.execute("SELECT pg_sleep(1)")


def test_exact_vectors_filter_before_limit_restart_and_batch_atomicity(database):
    store = PostgresVectorStore(database=database)
    store.ensure("first", 2)
    private, public = str(uuid4()), str(uuid4())
    store.upsert("first", (VectorPoint(private, (1, 0)), VectorPoint(public, (1, 1))))
    result = store.search("first", (1, 0), allowed_ids=(public,), limit=1)
    assert result[0].id == public
    assert result[0].score == pytest.approx(2**-0.5)
    restarted = PostgresVectorStore(
        database=PostgresDatabase(database._dsn, schema=database.schema)
    )
    assert restarted.search("first", (1, 0), allowed_ids=(public,), limit=1) == result
    assert store.search("first", (1, 0), allowed_ids=(), limit=1) == ()
    with pytest.raises(VectorValidationError):
        store.upsert("first", (VectorPoint(public, (0, 1)), VectorPoint("invalid", (1, 0))))
    assert restarted.search("first", (1, 0), allowed_ids=(public,), limit=1) == result
    store.delete("first", (public,))
    store.delete("first", (public,))
    assert store.search("first", (1, 0), allowed_ids=(public,), limit=1) == ()
    with pytest.raises(RuntimeError, match="dimensions"):
        store.ensure("first", 3)
