"""Exercise the same lexical projection contract on SQLite and PostgreSQL."""

import os
from uuid import uuid4

import pytest

from galmuri.documents.lexical.schema import SCHEMA as LEXICAL_SCHEMA
from galmuri.execution.persistence.schema import SCHEMA
from galmuri.storage.database import Database


@pytest.fixture(params=("sqlite", "postgres"))
def database(request, tmp_path):
    if request.param == "sqlite":
        database = Database(tmp_path / "documents.db")
        database.initialize(SCHEMA)
        database.initialize(LEXICAL_SCHEMA)
        yield database
        return
    driver = pytest.importorskip("psycopg")
    dsn = os.environ.get("FRAMEWORK_POSTGRES_DSN")
    if not dsn:
        pytest.skip("FRAMEWORK_POSTGRES_DSN is not configured")
    from galmuri.storage.postgres import PostgresDatabase

    schema = "lexical_test_" + uuid4().hex
    database = PostgresDatabase(dsn, schema=schema)
    database.initialize(SCHEMA)
    database.initialize(LEXICAL_SCHEMA)
    try:
        yield database
    finally:
        with driver.connect(dsn, autocommit=True) as connection:
            connection.execute('DROP SCHEMA "' + schema + '" CASCADE')
