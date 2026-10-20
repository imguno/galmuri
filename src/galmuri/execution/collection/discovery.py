"""Durable discovery handoff; policies decide what to collect and when."""

import uuid

from galmuri.contracts.files import ChangeSet
from galmuri.execution.lifecycle.intents import enqueue


class Discovery:
    def __init__(self, database, apps, clock):
        self.database, self.apps, self.clock = database, apps, clock

    def collect(self, name, force=False):
        app = self.apps[name]
        token = uuid.uuid4().hex
        with self.database.transaction() as connection:
            now = self.clock()
            state = connection.execute("SELECT * FROM app_state WHERE name=?", (name,)).fetchone()
            if state["revision"] != app.revision:
                return {"app": name, "enqueued": 0, "state": "STALE"}
            if state["paused"] or (not force and state["next_collection"] > now):
                return {
                    "app": name,
                    "enqueued": 0,
                    "state": "PAUSED" if state["paused"] else "WAITING",
                }
            if state["collection_token"] and state["collection_until"] > now:
                return {"app": name, "enqueued": 0, "state": "DISCOVERING"}
            checkpoint = state["checkpoint"]
            connection.execute(
                "UPDATE app_state SET collection_token=?,collection_until=?,"
                "collection_state='DISCOVERING',collection_error=NULL WHERE name=?",
                (token, now + app.policy.lease_seconds, name),
            )
        try:
            changes = app.policy.discover(app.source, checkpoint)
            if not isinstance(changes, ChangeSet):
                raise TypeError("Discovery must return ChangeSet")
            with self.database.transaction() as connection:
                state = connection.execute(
                    "SELECT * FROM app_state WHERE name=?", (name,)
                ).fetchone()
                # Collection has no publication side effects: an expired lease permits reclaim,
                # but the same token can still commit if no collector actually replaced it.
                # Token/revision CAS inside this transaction fences every reclaimed result.
                if (
                    state["collection_token"] != token
                    or state["paused"]
                    or state["revision"] != app.revision
                ):
                    return {"app": name, "enqueued": 0, "state": "STALE"}
                count = sum(
                    enqueue(connection, app, change, self.clock()) for change in changes.changes
                )
                connection.execute(
                    "UPDATE app_state SET checkpoint=?,next_collection=?,collection_token=NULL,"
                    "collection_until=NULL,collection_state=? WHERE name=?",
                    (
                        changes.checkpoint,
                        self.clock() + (app.policy.interval if changes.complete else 0),
                        "COMPLETE" if changes.complete else "PLANNED",
                        name,
                    ),
                )
                return {
                    "app": name,
                    "enqueued": count,
                    "state": "COMPLETE" if changes.complete else "PLANNED",
                }
        except Exception as error:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE app_state SET collection_state='RETRY_WAIT',collection_error=?,"
                    "collection_token=NULL,collection_until=NULL,next_collection=? "
                    "WHERE name=? AND collection_token=?",
                    (str(error), self.clock() + app.policy.retry_delay, name, token),
                )
            raise
