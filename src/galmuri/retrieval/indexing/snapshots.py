"""One authoritative eligibility fence shared by publication and search."""

import hashlib
import json
from contextlib import closing


def snapshot(row):
    body = {key: row[key] for key in ("key", "source_key", "version", "text", "metadata")}
    body["revision"] = row["revision"]
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), encoded


def current_documents(connection, app, key=None, *, keys=None):
    if keys is not None:
        keys = tuple(dict.fromkeys(keys))
        rows = []
        for start in range(0, len(keys), 400):
            selected = keys[start : start + 400]
            rows.extend(
                connection.execute(
                    "SELECT d.*,a.revision FROM documents d "
                    "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
                    "JOIN app_state a ON a.name=d.app "
                    "WHERE d.app=? AND d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version "
                    "AND d.key IN (" + ",".join("?" for _ in selected) + ") ORDER BY d.key",
                    (app, *selected),
                ).fetchall()
            )
        return rows
    return connection.execute(
        "SELECT d.*,a.revision FROM documents d "
        "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
        "JOIN app_state a ON a.name=d.app "
        "WHERE d.app=? AND d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version "
        + ("AND d.key=? " if key is not None else "")
        + "ORDER BY d.key",
        (app, key) if key is not None else (app,),
    ).fetchall()


def has_visible_vectors(connection, app, principal):
    """Inspect publication/permission headers before spending inference or store IO."""
    statement = (
        "SELECT d.readers FROM semantic_heads h "
        "JOIN semantic_builds b ON b.id=h.build "
        "JOIN documents d ON d.app=h.app AND d.key=h.key "
        "JOIN source_refs s ON s.app=d.app AND s.key=d.source_key "
        "WHERE h.app=? AND b.state='PUBLISHED' AND b.fingerprint=? AND b.revision=? "
        "AND b.prepared IS NOT NULL AND b.prepared<>'[]' "
        "AND d.state='ACTIVE' AND s.deleted=0 AND s.version=d.version"
    )
    parameters = (app.name, app.retrieval.fingerprint, app.revision)
    stream = getattr(connection, "stream", None)
    cursor = (
        stream(statement, parameters)
        if stream is not None
        else closing(connection.execute(statement, parameters))
    )
    with cursor as rows:
        return any(principal.matches(json.loads(row["readers"])) for row in rows)


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
