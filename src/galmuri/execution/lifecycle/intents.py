"""Atomic registration of observed source versions and durable execution intents."""

import json
import uuid

from galmuri.documents.lexical.projection import retire_source as retire_lexical_source
from galmuri.documents.lifecycle import retire_source
from galmuri.execution.lifecycle.transitions import event, finish


def enqueue(connection, app, change, now):
    ref = change.ref
    prior = connection.execute(
        "SELECT * FROM source_refs WHERE app=? AND key=?", (app.name, ref.key)
    ).fetchone()
    unchanged = prior and prior["version"] == ref.version and prior["deleted"] == change.deleted
    if unchanged:
        existing = connection.execute(
            "SELECT 1 FROM jobs WHERE app=? AND source_key=? AND version=? AND revision=? "
            "AND deleted=? LIMIT 1",
            (app.name, ref.key, ref.version, app.revision, change.deleted),
        ).fetchone()
        if existing:
            return False
    identity = uuid.uuid4().hex
    connection.execute(
        "INSERT INTO source_refs(app,key,version,metadata,deleted) VALUES(?,?,?,?,?) "
        "ON CONFLICT(app,key) DO UPDATE SET version=excluded.version,"
        "metadata=excluded.metadata,deleted=excluded.deleted",
        (app.name, ref.key, ref.version, json.dumps(ref.metadata), change.deleted),
    )
    old_jobs = connection.execute(
        "SELECT * FROM jobs WHERE app=? AND source_key=? "
        "AND state IN ('READY','RUNNING','RETRY_WAIT')",
        (app.name, ref.key),
    ).fetchall()
    for old in old_jobs:
        finish(connection, old, "SUPERSEDED", now, "Newer source intent accepted")
    if change.deleted:
        retire_source(connection, app.name, ref.key, deleted=True)
    else:
        # A newer desired version immediately stops contributing searchable terms.
        retire_lexical_source(connection, app.name, ref.key)
    connection.execute(
        "INSERT INTO jobs(id,app,source_key,version,metadata,revision,deleted,state,available,"
        "created,updated) VALUES(?,?,?,?,?,?,?,'READY',?,?,?)",
        (
            identity,
            app.name,
            ref.key,
            ref.version,
            json.dumps(ref.metadata),
            app.revision,
            change.deleted,
            now,
            now,
            now,
        ),
    )
    event(connection, {"id": identity, "app": app.name}, "READY", "Source intent accepted", now)
    return True
