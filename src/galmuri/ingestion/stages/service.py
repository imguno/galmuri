"""Read acceptance, parsing acceptance and document preparation have separate retries."""

import json
from dataclasses import asdict

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File, FileRef, SourceConflict
from galmuri.ingestion.stages.ownership import identity, require_owned
from galmuri.ingestion.stages.pipeline import PipelineStages
from galmuri.processing.pipeline import Pipeline


class Ingestion:
    def __init__(self, database, clock):
        self.database, self.clock = database, clock

    def _load(self, job, app):
        fingerprint = identity(job, app)
        with self.database.transaction() as connection:
            require_owned(connection, job, app, self.clock())
            row = connection.execute(
                "SELECT * FROM ingestion_checkpoints WHERE job=?", (job["id"],)
            ).fetchone()
            if row is not None and row["identity"] != fingerprint:
                raise ValueError("Ingestion configuration changed; activate a new app revision")
            connection.execute(
                "INSERT INTO ingestion_checkpoints(job,app,identity,updated) "
                "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                (job["id"], job["app"], fingerprint, self.clock()),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM ingestion_checkpoints WHERE job=?", (job["id"],)
                ).fetchone()
            )

    def _save(self, job, app, stage, **values):
        with self.database.transaction() as connection:
            require_owned(connection, job, app, self.clock())
            columns = ["stage=?", "error=NULL", "updated=?"] + [key + "=?" for key in values]
            connection.execute(
                "UPDATE ingestion_checkpoints SET " + ",".join(columns) + " WHERE job=?",
                (stage, self.clock(), *values.values(), job["id"]),
            )

    def run(self, job, app):
        self.release_completed()
        checkpoint = self._load(job, app)
        ref = FileRef(job["source_key"], job["version"], json.loads(job["metadata"]))
        try:
            if checkpoint["content"] is None:
                file = app.source.read(ref)
                if not isinstance(file, File) or not isinstance(file.content, bytes):
                    raise TypeError("Source read() must return File with bytes content")
                if file.ref.key != ref.key or file.ref.version != ref.version:
                    raise SourceConflict("Source read returned a different identity or version")
                self._save(
                    job,
                    app,
                    "PARSING",
                    content=file.content,
                    file_metadata=json.dumps(file.ref.metadata, allow_nan=False),
                )
            else:
                file = File(
                    FileRef(ref.key, ref.version, json.loads(checkpoint["file_metadata"])),
                    checkpoint["content"],
                )
            if isinstance(app.handler, Pipeline):
                result = PipelineStages(self.database, self.clock).run(job, app, file)
                self._save(job, app, "PREPARED")
                return result
            if checkpoint["parsed"] is None:
                documents = app.handler.parse(file)
                encoded = json.dumps([asdict(document) for document in documents], allow_nan=False)
                self._save(job, app, "PREPARING", parsed=encoded)
            else:
                documents = tuple(
                    Document(
                        **(
                            value
                            | {
                                "readers": tuple(value["readers"]),
                                "writers": tuple(value["writers"]),
                            }
                        )
                    )
                    for value in json.loads(checkpoint["parsed"])
                )
            result = app.handler.prepare(documents)
            self._save(job, app, "PREPARED")
            return result
        except Exception as error:
            with self.database.transaction() as connection:
                try:
                    require_owned(connection, job, app, self.clock())
                except RuntimeError:
                    pass
                else:
                    connection.execute(
                        "UPDATE ingestion_checkpoints SET error=?,updated=? WHERE job=?",
                        (str(error), self.clock(), job["id"]),
                    )
            raise

    def release_completed(self):
        """Confirmed terminal jobs no longer need private source/parse retry payloads."""
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM ingestion_step_checkpoints WHERE job IN "
                "(SELECT id FROM jobs WHERE state IN ('SUCCEEDED','CANCELLED','SUPERSEDED'))"
            )
            connection.execute(
                "UPDATE ingestion_checkpoints SET content=NULL,file_metadata=NULL,parsed=NULL,"
                "updated=?,stage=CASE (SELECT state FROM jobs WHERE id=job) "
                "WHEN 'SUCCEEDED' THEN 'PUBLISHED' "
                "ELSE (SELECT state FROM jobs WHERE id=job) END "
                "WHERE stage NOT IN ('PUBLISHED','CANCELLED','SUPERSEDED') AND job IN "
                "(SELECT id FROM jobs WHERE state IN ('SUCCEEDED','CANCELLED','SUPERSEDED'))",
                (self.clock(),),
            )

    def status(self, app_name=None):
        with self.database.connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT c.job,c.app,c.stage,c.error,c.updated,j.state AS job_state "
                    "FROM ingestion_checkpoints c JOIN jobs j ON j.id=c.job "
                    + ("WHERE c.app=? " if app_name else "")
                    + "ORDER BY c.updated,c.job",
                    (app_name,) if app_name else (),
                )
            ]
