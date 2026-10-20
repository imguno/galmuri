"""Portable connection contracts and safe PostgreSQL configuration."""

import time

import pytest

from galmuri.storage.database import Database
from galmuri.storage.errors import StorageError
from galmuri.storage.postgres import PostgresDatabase
from galmuri.storage.postgres_rows import Row
from galmuri.storage.postgres_sql import placeholders


def test_row_supports_positional_access_and_mapping_conversion():
    row = Row(("id", "name"), (12, "hello"))
    assert row[0] == row["id"] == 12
    assert row[1:] == ("hello",)
    assert dict(row) == {"id": 12, "name": "hello"}


def test_placeholder_translation_preserves_sql_literals_comments_and_dollar_quotes():
    source = "SELECT ?, '?', \"?\", 'it''s ? 50%', $$?$$, $body$?$body$ -- ?\n/* ? */ ?"
    expected = "SELECT %s, '?', \"?\", 'it''s ? 50%%', $$?$$, $body$?$body$ -- ?\n/* ? */ %s"
    assert placeholders(source) == expected


def test_postgres_identity_redacts_credentials_and_does_not_connect(monkeypatch):
    driver = pytest.importorskip("psycopg")
    monkeypatch.setattr(driver, "connect", lambda *a, **k: pytest.fail("construction connected"))
    first = PostgresDatabase("host=localhost dbname=app user=alice password=topsecret")
    second = PostgresDatabase("host=localhost dbname=app user=bob password=newsecret")
    assert first.identity == second.identity
    assert "topsecret" not in first.identity + repr(first)
    assert "alice" not in first.identity
    assert PostgresDatabase("host=elsewhere dbname=app").identity != first.identity
    assert PostgresDatabase("host=localhost dbname=app", schema="other").identity != first.identity


@pytest.mark.parametrize("schema", ["public; DROP TABLE docs", "abc.def", "", "ä", "x" * 64])
def test_invalid_schema_rejected_before_connection(schema):
    with pytest.raises(ValueError, match="identifiers"):
        PostgresDatabase("dbname=app", schema=schema)


def test_malformed_connection_errors_hide_dsn():
    pytest.importorskip("psycopg")
    with pytest.raises(StorageError) as error:
        PostgresDatabase("password=topsecret invalidsyntax")
    assert "topsecret" not in str(error.value)
    assert error.value.__cause__ is None


def test_connect_failure_hides_driver_dsn_diagnostics(monkeypatch):
    driver = pytest.importorskip("psycopg")
    database = PostgresDatabase("host=localhost dbname=app password=topsecret")

    def fail(*args, **kwargs):
        raise RuntimeError("password=topsecret connection refused")

    monkeypatch.setattr(driver, "connect", fail)
    with pytest.raises(StorageError, match="Could not connect") as error:
        with database.connection():
            pytest.fail("Connection failure yielded a scope")
    assert "topsecret" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("value", [0, -1, True, None, float("inf"), float("nan"), 86401])
def test_unbounded_or_invalid_timeouts_rejected(value):
    with pytest.raises(ValueError, match="timeouts"):
        PostgresDatabase("dbname=app", lock_timeout=value)


def test_sqlite_snapshot_and_columns_contract(tmp_path):
    database = Database(tmp_path / "state.sqlite")
    database.initialize("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    with database.transaction() as connection:
        connection.execute("INSERT INTO sample VALUES (?,?)", (1, "first"))
    with database.snapshot() as connection:
        assert database.columns(connection, "sample") == {"id", "value"}
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "first"
        with database.transaction() as other:
            other.execute("UPDATE sample SET value='second'")
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "first"
    with database.connection() as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "second"
    assert database.now() == pytest.approx(time.time(), abs=2)
