"""Coherent relational lifecycle bundle shared by concrete persistence adapters."""

from galmuri.documents.publication import Publication
from galmuri.documents.queries import Queries
from galmuri.documents.writes import Writes
from galmuri.execution.collection.discovery import Discovery
from galmuri.execution.lifecycle.queue import Queue
from galmuri.execution.lifecycle.state import State
from galmuri.execution.persistence.schema import SCHEMA
from galmuri.execution.ports import RuntimeComponents
from galmuri.ingestion.stages.schema import SCHEMA as INGESTION_SCHEMA
from galmuri.ingestion.stages.service import Ingestion
from galmuri.retrieval.indexing import Indexing
from galmuri.retrieval.indexing.reconciliation import activate as activate_retrieval
from galmuri.retrieval.indexing.schema import SCHEMA as INDEX_SCHEMA


def open_relational(database, apps, clock, *, activate=False):
    for schema in (SCHEMA, INDEX_SCHEMA, INGESTION_SCHEMA):
        database.initialize(schema)
    with database.transaction() as connection:
        columns = database.columns(connection, "app_state")
        if "source_identity" not in columns:
            connection.execute("ALTER TABLE app_state ADD COLUMN source_identity TEXT")
        columns = database.columns(connection, "writes")
        for column in ("revision", "source_identity"):
            if column not in columns:
                connection.execute(f"ALTER TABLE writes ADD COLUMN {column} TEXT")
    state = State(
        database,
        apps,
        clock,
        activate=activate,
        on_activate=lambda connection: activate_retrieval(connection, apps, explicit=activate),
    )
    return RuntimeComponents(
        database=database,
        queue=Queue(database, apps, clock),
        discovery=Discovery(database, apps, clock),
        documents=Publication(database, clock),
        queries=Queries(database),
        writes=Writes(database, apps, clock),
        state=state,
        indexing=Indexing(database, apps, clock),
        ingestion=Ingestion(database, clock),
    )
