"""Index request admission is atomic with its accepted generation IDs."""

import hashlib
import json

from galmuri.contracts.requests import RequestConflict


def identity(apps, app_name, request_id):
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
        raise ValueError("request_id must contain 1..200 characters")
    targets = sorted(name for name in apps if app_name is None or name == app_name)
    key = json.dumps(["reindex", targets, app_name, request_id])
    configuration = [
        [
            name,
            apps[name].revision,
            apps[name].retrieval.fingerprint if apps[name].retrieval else None,
        ]
        for name in targets
    ]
    return hashlib.sha256(key.encode()).hexdigest(), json.dumps(configuration, sort_keys=True)


def replay(connection, key, fingerprint):
    row = connection.execute(
        "SELECT * FROM semantic_requests WHERE request_key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    if row["fingerprint"] != fingerprint:
        raise RequestConflict(
            "Request identity has already been used with a different configuration"
        )
    return json.loads(row["result"])


def record(connection, key, fingerprint, result, now):
    connection.execute(
        "INSERT INTO semantic_requests VALUES(?,?,?,?)", (key, fingerprint, json.dumps(result), now)
    )
