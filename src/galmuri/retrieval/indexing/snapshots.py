"""One authoritative eligibility fence shared by publication and search."""

import hashlib
import json


def snapshot(row):
    body = {key: row[key] for key in ("key", "source_key", "version", "text", "metadata")}
    body["revision"] = row["revision"]
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), encoded


def current_documents(connection, app, key=None):
    return connection.execute(
        "SELECT d.*,a.revision FROM documents d "
        "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
        "JOIN app_state a ON a.name=d.app "
        "WHERE d.app=? AND d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version "
        + ("AND d.key=? " if key is not None else "")
        + "ORDER BY d.key",
        (app, key) if key is not None else (app,),
    ).fetchall()


def active_config(connection, app):
    return connection.execute("SELECT * FROM semantic_configs WHERE app=?", (app,)).fetchone()


def compatible(connection, app):
    row = active_config(connection, app.name)
    state = connection.execute(
        "SELECT revision FROM app_state WHERE name=?", (app.name,)
    ).fetchone()
    fingerprint = app.retrieval.fingerprint if app.retrieval else None
    return (
        row is not None
        and state is not None
        and state["revision"] == app.revision
        and row["fingerprint"] == fingerprint
        and row["revision"] == app.revision
    )


def current_build(connection, job, now=None):
    config = active_config(connection, job["app"])
    if (
        config is None
        or config["fingerprint"] != job["fingerprint"]
        or config["revision"] != job["revision"]
    ):
        return False
    head = connection.execute(
        "SELECT build FROM semantic_heads WHERE app=? AND key=?", (job["app"], job["key"])
    ).fetchone()
    if head is None or head["build"] != job["id"]:
        return False
    return any(
        row["key"] == job["key"] and snapshot(row)[0] == job["snapshot"]
        for row in current_documents(connection, job["app"], job["key"])
    )


def namespace(fingerprint):
    return "semantic_" + fingerprint


def cleanup(connection, job, now):
    connection.execute(
        "INSERT INTO semantic_cleanup(build,app,fingerprint,available) VALUES(?,?,?,?) "
        "ON CONFLICT(build) DO UPDATE SET state='READY',available=excluded.available,"
        "token=NULL,lease_until=NULL",
        (job["id"], job["app"], job["fingerprint"], now),
    )


def supersede(connection, job, now):
    connection.execute(
        "UPDATE semantic_builds SET state='SUPERSEDED',updated=? WHERE id=?", (now, job["id"])
    )
    cleanup(connection, job, now)
