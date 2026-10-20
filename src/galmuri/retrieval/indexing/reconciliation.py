"""Reconcile durable publications, never relying on in-process callbacks."""

import uuid

from galmuri.retrieval.indexing import requests
from galmuri.retrieval.indexing.snapshots import (
    active_config,
    compatible,
    current_documents,
    snapshot,
    supersede,
)


def activate(connection, apps, *, explicit=False):
    """Runs inside the same transaction that activates source/app revisions."""
    for app in apps.values():
        fingerprint = app.retrieval.fingerprint if app.retrieval else None
        prior = active_config(connection, app.name)
        if prior and (prior["fingerprint"] != fingerprint or prior["revision"] != app.revision):
            if not explicit:
                raise ValueError("Retrieval configuration differs; use activate=True explicitly")
        connection.execute(
            "INSERT INTO semantic_configs(app,fingerprint,revision) VALUES(?,?,?) "
            "ON CONFLICT(app) DO UPDATE SET fingerprint=excluded.fingerprint,"
            "revision=excluded.revision",
            (app.name, fingerprint, app.revision),
        )


def reconcile(database, apps, clock, app_name=None, *, rebuild=False, request_id=None):
    scheduled = []
    request = requests.identity(apps, app_name, request_id) if request_id is not None else None
    with database.transaction() as connection:
        now = clock()
        if request is not None:
            prior = requests.replay(connection, *request)
            if prior is not None:
                return prior
        for app in apps.values():
            if app_name is not None and app.name != app_name:
                continue
            if not compatible(connection, app):
                continue  # Old coordinators cannot overwrite the active configuration.
            documents = {row["key"]: row for row in current_documents(connection, app.name)}
            heads = connection.execute(
                "SELECT b.id,b.app,b.key,b.fingerprint,b.revision,b.snapshot "
                "FROM semantic_heads h JOIN semantic_builds b ON b.id=h.build "
                "WHERE h.app=?",
                (app.name,),
            ).fetchall()
            retained = set()
            for job in heads:
                document = documents.get(job["key"])
                valid = (
                    app.retrieval is not None
                    and document is not None
                    and job["fingerprint"] == app.retrieval.fingerprint
                    and job["revision"] == app.revision
                    and job["snapshot"] == snapshot(document)[0]
                )
                if valid and not rebuild:
                    retained.add(job["key"])
                    continue
                supersede(connection, job, now)
                connection.execute(
                    "DELETE FROM semantic_heads WHERE app=? AND key=?", (app.name, job["key"])
                )
            if app.retrieval is None:
                continue
            for key, document in documents.items():
                if key in retained:
                    continue
                digest, body = snapshot(document)
                identity = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO semantic_builds(id,app,key,fingerprint,store_identity,"
                    "revision,snapshot,body,"
                    "state,available,created,updated) VALUES(?,?,?,?,?,?,?,?,'READY',?,?,?)",
                    (
                        identity,
                        app.name,
                        key,
                        app.retrieval.fingerprint,
                        app.retrieval.store.identity,
                        app.revision,
                        digest,
                        body,
                        now,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO semantic_heads(app,key,build) VALUES(?,?,?)",
                    (app.name, key, identity),
                )
                scheduled.append(identity)
        result = {"scheduled": len(scheduled), "jobs": scheduled}
        if request is not None:
            requests.record(connection, *request, result, now)
    return result
