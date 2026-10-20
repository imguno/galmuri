"""Execution transition journal shared by queue and guarded publication."""

TRANSITIONS = {
    "READY": {"RUNNING", "CANCELLED", "SUPERSEDED"},
    "RUNNING": {"SUCCEEDED", "RETRY_WAIT", "RECONCILING", "FAILED", "SUPERSEDED"},
    "RETRY_WAIT": {"READY", "RUNNING", "CANCELLED", "SUPERSEDED"},
    "RECONCILING": {"RECONCILING", "RETRY_WAIT", "FAILED", "CANCELLED", "SUPERSEDED"},
    "FAILED": {"READY"},
    "SUCCEEDED": set(),
    "CANCELLED": set(),
    "SUPERSEDED": set(),
}


def event(connection, job, state, message, now):
    connection.execute(
        "INSERT INTO events(job_id,app,at,state,message) VALUES(?,?,?,?,?)",
        (job["id"], job["app"], now, state, message),
    )


def require_transition(job, state):
    if state not in TRANSITIONS.get(job["state"], set()):
        raise ValueError(f"Invalid execution transition: {job['state']} -> {state}")


def finish(connection, job, state, now, error=None, available=None):
    require_transition(job, state)
    connection.execute(
        "UPDATE jobs SET state=?,error=?,updated=?,available=COALESCE(?,available),"
        "token=NULL,lease_until=NULL WHERE id=?",
        (state, error, now, available, job["id"]),
    )
    if job["token"]:
        connection.execute(
            "UPDATE attempts SET ended=?,outcome=?,error=? WHERE token=? AND ended IS NULL",
            (now, state, error, job["token"]),
        )
    event(connection, job, state, error or state.lower(), now)
