"""PostgreSQL lifecycle backend; instances coordinate through short DB transactions."""

import time

from galmuri.execution.persistence.composition import open_relational
from galmuri.storage.postgres import PostgresDatabase


class PostgresBackend:
    def __init__(self, dsn, *, schema="public", **options):
        self.database = PostgresDatabase(dsn, schema=schema, **options)
        self.identity = self.database.identity

    def default_store(self, app=None):
        from galmuri.retrieval.stores.postgres import PostgresVectorStore

        return PostgresVectorStore(database=self.database)

    def open(self, apps, clock, *, activate=False):
        clock = self.database.now if clock is time.time else clock
        return open_relational(self.database, apps, clock, activate=activate)
