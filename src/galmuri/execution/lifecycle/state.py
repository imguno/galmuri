"""Default app activation and execution ownership projection store."""

from galmuri.documents.lifecycle import retire_app
from galmuri.execution.lifecycle.transitions import finish
from galmuri.execution.persistence.status import status


class State:
    def __init__(self, database, apps, clock, *, activate=False, on_activate=None):
        self.database = database
        with database.transaction() as connection:
            for app in apps.values():
                source_type = type(app.source)
                identity = getattr(app.source, "identity", None)
                identity_declared = identity is not None
                identity = (
                    str(identity)
                    if identity is not None
                    else (source_type.__module__ + "." + source_type.__qualname__)
                )
                prior = connection.execute(
                    "SELECT * FROM app_state WHERE name=?", (app.name,)
                ).fetchone()
                switched = prior and prior["source_identity"] not in {None, identity}
                if switched and prior["revision"] == app.revision:
                    raise ValueError("Source identity changed; increment the app revision")
                if prior and prior["revision"] != app.revision:
                    if not activate:
                        raise ValueError(
                            "App revision differs from active revision; "
                            "use explicit activate=True to replace it"
                        )
                    retire_app(
                        connection,
                        app.name,
                        reset_permissions=bool(switched) or not identity_declared,
                    )
                    pending = connection.execute(
                        "SELECT * FROM jobs WHERE app=? "
                        "AND state IN ('READY','RUNNING','RETRY_WAIT')",
                        (app.name,),
                    ).fetchall()
                    for job in pending:
                        finish(connection, job, "SUPERSEDED", clock(), "App revision replaced")
                    connection.execute(
                        "UPDATE app_state SET checkpoint=NULL,next_collection=0,"
                        "collection_token=NULL,collection_until=NULL,collection_state='PLANNED' "
                        "WHERE name=?",
                        (app.name,),
                    )
                connection.execute(
                    "INSERT INTO app_state(name,revision,source_identity) VALUES(?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET revision=excluded.revision,"
                    "source_identity=excluded.source_identity",
                    (app.name, app.revision, identity),
                )
            if on_activate is not None:
                on_activate(connection)

    def owned(self, claim):
        with self.database.connection() as connection:
            current = connection.execute("SELECT * FROM jobs WHERE id=?", (claim["id"],)).fetchone()
            if (
                current is None
                or current["state"] != "RUNNING"
                or current["token"] != claim["token"]
            ):
                return None
            return dict(current)

    def pause(self, name, paused):
        with self.database.transaction() as connection:
            connection.execute("UPDATE app_state SET paused=? WHERE name=?", (paused, name))

    def status(self, app_name=None):
        return status(self.database, app_name)
