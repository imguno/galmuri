"""Store-independent embedding values; point IDs belong to publication generations."""

import hashlib
import json
import uuid
from dataclasses import asdict

from galmuri.retrieval.indexing.claims import owned


def identity(config, job):
    body = json.loads(job["body"])
    value = {
        "text": body["text"],
        "embedding": asdict(config.embedding.spec),
        "chunker": config.chunker.identity,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(database, config, job, clock, build):
    fingerprint = identity(config, job)
    with database.transaction() as connection:
        if not owned(connection, job, clock()):
            raise RuntimeError("Embedding artifact claim is no longer active")
        row = connection.execute(
            "SELECT prepared FROM semantic_artifacts WHERE app=? AND key=? AND identity=?",
            (job["app"], job["key"], fingerprint),
        ).fetchone()
    values = (
        json.loads(row["prepared"])
        if row
        else [
            {key: value for key, value in item.items() if key != "id"}
            for item in build(config, job)
        ]
    )
    with database.transaction() as connection:
        if not owned(connection, job, clock()):
            raise RuntimeError("Embedding artifact claim is no longer active")
        if row is None:
            connection.execute(
                "INSERT INTO semantic_artifacts(app,key,identity,prepared,created) "
                "VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                (job["app"], job["key"], fingerprint, json.dumps(values), clock()),
            )
    # Never reuse IDs belonging to an older generation or another vector namespace.
    return [value | {"id": str(uuid.uuid4())} for value in values]
