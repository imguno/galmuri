"""Accepted step snapshots belong to ingestion; callbacks never own publication."""

from galmuri.ingestion.stages.ownership import require_owned
from galmuri.processing.values import decode, encode, snapshot


class PipelineStages:
    def __init__(self, database, clock):
        self.database, self.clock = database, clock

    def run(self, job, app, file):
        value = snapshot("file", file)
        for position, step in enumerate(app.handler.steps):
            with self.database.transaction() as connection:
                require_owned(connection, job, app, self.clock())
                row = connection.execute(
                    "SELECT * FROM ingestion_step_checkpoints WHERE job=? AND position=?",
                    (job["id"], position),
                ).fetchone()
                if row is not None:
                    if row["identity"] != step.fingerprint or row["kind"] != step.returns:
                        raise ValueError("Pipeline stage changed; activate a new app revision")
                    value = decode(row["kind"], row["payload"])
                    continue
                connection.execute(
                    "UPDATE ingestion_checkpoints SET stage=?,error=NULL,updated=? WHERE job=?",
                    ("STEP:" + step.name, self.clock(), job["id"]),
                )
            # Code and external IO execute outside the metadata transaction. At-least-once
            # invocation is intentional: a crash before acceptance may repeat this call.
            value = snapshot(step.returns, step.process(value))
            if step.returns == "file" and (
                value.ref.key != file.ref.key or value.ref.version != file.ref.version
            ):
                raise ValueError(
                    "File transforms must preserve the accepted file identity and version"
                )
            payload = encode(step.returns, value)
            with self.database.transaction() as connection:
                require_owned(connection, job, app, self.clock())
                connection.execute(
                    "INSERT INTO ingestion_step_checkpoints "
                    "(job,position,name,identity,kind,payload,updated) VALUES(?,?,?,?,?,?,?)",
                    (
                        job["id"],
                        position,
                        step.name,
                        step.fingerprint,
                        step.returns,
                        payload,
                        self.clock(),
                    ),
                )
        return value
