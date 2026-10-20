"""Lease transitions and token fencing; no provider calls in transactions."""

import uuid

from galmuri.retrieval.indexing.snapshots import compatible, current_build, supersede


def claim(database, apps, clock, worker, app_name=None):
    with database.transaction() as connection:
        now = clock()
        rows = connection.execute(
            "SELECT * FROM semantic_builds "
            "WHERE state IN ('READY','RETRY_WAIT','EMBEDDING','STORING') "
            "AND available<=? ORDER BY created,id",
            (now,),
        ).fetchall()
        for row in rows:
            app = apps.get(row["app"])
            if app is None or app.retrieval is None or (app_name and app.name != app_name):
                continue
            if not compatible(connection, app):
                continue
            paused = connection.execute(
                "SELECT paused FROM app_state WHERE name=?", (app.name,)
            ).fetchone()
            if paused is None or paused["paused"]:
                continue
            if row["lease_until"] is not None and row["lease_until"] > now:
                continue
            if not current_build(connection, row):
                supersede(connection, row, now)
                continue
            if row["attempts"] >= app.retrieval.max_attempts:
                connection.execute(
                    "UPDATE semantic_builds SET state='FAILED',token=NULL,lease_until=NULL,"
                    "error='Attempt limit reached after expired claim',updated=? WHERE id=?",
                    (now, row["id"]),
                )
                continue
            token = str(uuid.uuid4())
            connection.execute(
                "UPDATE semantic_builds SET state=stage,token=?,worker=?,lease_until=?,"
                "attempts=attempts+1,updated=? WHERE id=?",
                (token, worker, now + app.retrieval.lease_seconds, now, row["id"]),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM semantic_builds WHERE id=?", (row["id"],)
                ).fetchone()
            )
    return None


def owned(connection, job, now):
    row = connection.execute("SELECT * FROM semantic_builds WHERE id=?", (job["id"],)).fetchone()
    return (
        row is not None
        and row["token"] == job["token"]
        and row["state"] in {"EMBEDDING", "STORING"}
        and row["lease_until"] is not None
        and row["lease_until"] > now
        and current_build(connection, row)
    )


def heartbeat(database, job, clock, seconds):
    with database.transaction() as connection:
        now = clock()
        if not owned(connection, job, now):
            return False
        connection.execute(
            "UPDATE semantic_builds SET lease_until=? WHERE id=? AND token=?",
            (now + seconds, job["id"], job["token"]),
        )
        return True
