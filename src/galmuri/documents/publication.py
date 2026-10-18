"""The only default publication boundary; stale work never changes visible documents."""

import json

from galmuri.contracts.results import IngestResult
from galmuri.documents.lifecycle import retire_source
from galmuri.execution.lifecycle.transitions import finish


class Publication:
    def __init__(self, database, clock):
        self.database, self.clock = database, clock

    def publish(self, job, result):
        if not isinstance(result, IngestResult):
            raise TypeError("Handlers must return IngestResult; logs are not completion signals")
        with self.database.transaction() as connection:
            now = self.clock()
            current = connection.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if current["state"] != "RUNNING" or current["token"] != job["token"]:
                return False
            if current["lease_until"] <= now:
                finish(connection, current, "RECONCILING", now, "Publication lease expired")
                return False
            source = connection.execute(
                "SELECT * FROM source_refs WHERE app=? AND key=?", (job["app"], job["source_key"])
            ).fetchone()
            app = connection.execute(
                "SELECT * FROM app_state WHERE name=?", (job["app"],)
            ).fetchone()
            if (
                source["version"] != job["version"]
                or source["deleted"] != job["deleted"]
                or app["revision"] != job["revision"]
            ):
                finish(connection, current, "SUPERSEDED", now, "Source or app intent changed")
                return False
            stale_permissions = source["acl_generation"] != job["acl_generation"]
            if stale_permissions:
                connection.execute(
                    "INSERT INTO events(job_id,app,at,state,message) VALUES(?,?,?,?,?)",
                    (
                        job["id"],
                        job["app"],
                        now,
                        "ACL_CONFLICT",
                        "Body accepted; stale permission proposals discarded",
                    ),
                )
            # Detect identity collisions before withdrawing anything from the old generation.
            for document in result.documents:
                existing = connection.execute(
                    "SELECT source_key FROM documents WHERE app=? AND key=?",
                    (job["app"], document.key),
                ).fetchone()
                if existing and existing["source_key"] != job["source_key"]:
                    raise ValueError("Document identity already belongs to another source file")
            retire_source(connection, job["app"], job["source_key"], deleted=bool(job["deleted"]))
            for document in () if job["deleted"] else result.documents:
                connection.execute(
                    "INSERT INTO documents(app,key,source_key,version,text,metadata,"
                    "readers,writers) "
                    "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(app,key) DO UPDATE SET "
                    "version=excluded.version,text=excluded.text,metadata=excluded.metadata,state='ACTIVE',"
                    "readers=CASE WHEN documents.acl_override=1 OR ?<>0 "
                    "THEN documents.readers ELSE excluded.readers END,"
                    "writers=CASE WHEN documents.acl_override=1 OR ?<>0 "
                    "THEN documents.writers ELSE excluded.writers END",
                    (
                        job["app"],
                        document.key,
                        job["source_key"],
                        job["version"],
                        document.text,
                        json.dumps(document.metadata),
                        json.dumps(() if stale_permissions else document.readers),
                        json.dumps(() if stale_permissions else document.writers),
                        stale_permissions,
                        stale_permissions,
                    ),
                )
            finish(connection, current, "SUCCEEDED", now)
            for message in result.messages:
                connection.execute(
                    "INSERT INTO events(job_id,app,at,state,message) VALUES(?,?,?,?,?)",
                    (job["id"], job["app"], now, "LOG", message),
                )
            return True

    def set_permissions(self, app, key, readers, writers, expected_revision=None):
        """Trusted internal command: independent ACL generation, never an admin data bypass."""
        with self.database.transaction() as connection:
            document = connection.execute(
                "SELECT * FROM documents WHERE app=? AND key=?", (app, key)
            ).fetchone()
            if document is None:
                raise KeyError(key)
            source = connection.execute(
                "SELECT * FROM source_refs WHERE app=? AND key=?", (app, document["source_key"])
            ).fetchone()
            if expected_revision is not None and source["acl_generation"] != expected_revision:
                raise ValueError("Permission generation conflict")
            connection.execute(
                "UPDATE source_refs SET acl_generation=acl_generation+1 WHERE app=? AND key=?",
                (app, document["source_key"]),
            )
            connection.execute(
                "UPDATE documents SET readers=?,writers=?,acl_override=1 WHERE app=? AND key=?",
                (json.dumps(tuple(readers)), json.dumps(tuple(writers)), app, key),
            )
            return source["acl_generation"] + 1
