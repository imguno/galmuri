"""A checkpoint cannot outlive the claim, source intent or active configuration."""

import hashlib
import json


class CheckpointRejected(RuntimeError):
    """No current claim exists to accept or reuse a private checkpoint."""


def source_identity(app):
    source_type = type(app.source)
    declared = getattr(app.source, "identity", None)
    return (
        str(declared)
        if declared is not None
        else (source_type.__module__ + "." + source_type.__qualname__)
    )


def identity(job, app):
    value = {
        "app": job["app"],
        "source": source_identity(app),
        "key": job["source_key"],
        "version": job["version"],
        "metadata": json.loads(job["metadata"]),
        "revision": job["revision"],
        "handler": app.handler.fingerprint,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def require_owned(connection, job, app, now):
    row = connection.execute(
        "SELECT j.state,j.token,j.lease_until,j.revision,a.revision AS active_revision,"
        "a.source_identity,r.version,r.deleted,r.acl_generation,r.metadata FROM jobs j "
        "JOIN app_state a ON a.name=j.app "
        "JOIN source_refs r ON r.app=j.app AND r.key=j.source_key WHERE j.id=?",
        (job["id"],),
    ).fetchone()
    if (
        row is None
        or row["state"] != "RUNNING"
        or row["token"] != job["token"]
        or row["lease_until"] is None
        or row["lease_until"] <= now
        or row["revision"] != app.revision
        or row["active_revision"] != app.revision
        or row["source_identity"] != source_identity(app)
        or row["version"] != job["version"]
        or row["deleted"] != job["deleted"]
        or row["acl_generation"] != job["acl_generation"]
        or json.loads(row["metadata"]) != json.loads(job["metadata"])
    ):
        raise CheckpointRejected("Ingestion checkpoint claim, source, configuration or ACL changed")
