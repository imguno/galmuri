"""Original-source writes are distinct from search publication."""

import json
import uuid

from galmuri.contracts.files import Change, EffectUnknown, FileRef, SourceConflict
from galmuri.execution.lifecycle.intents import enqueue


class Writes:
    def __init__(self, database, apps, clock):
        self.database, self.apps, self.clock = database, apps, clock

    def lookup(self, operation_id):
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM writes WHERE id=?", (operation_id,)).fetchone()
            return dict(row) if row else None

    def write(self, app_name, document_key, content, principal, expected_version):
        app = self.apps[app_name]
        if not app.writable:
            raise NotImplementedError("Source does not support writes")
        operation = uuid.uuid4().hex
        # Durable intent precedes the external call. A crash requires reconciliation.
        with self.database.transaction() as connection:
            definition = connection.execute(
                "SELECT revision,source_identity FROM app_state WHERE name=?", (app_name,)
            ).fetchone()
            if definition["revision"] != app.revision:
                raise SourceConflict("App revision is no longer active")
            document = connection.execute(
                "SELECT * FROM documents WHERE app=? AND key=? AND state='ACTIVE'",
                (app_name, document_key),
            ).fetchone()
            if document is None:
                raise PermissionError("Document unavailable")
            source_key = document["source_key"]
            self._authorize(connection, app_name, source_key, principal, expected_version)
            pending = connection.execute(
                "SELECT 1 FROM writes WHERE app=? AND source_key=? AND state='RECONCILING'",
                (app_name, source_key),
            ).fetchone()
            if pending:
                raise EffectUnknown("Prior write requires reconciliation")
            connection.execute(
                "INSERT INTO writes(id,app,source_key,expected_version,revision,source_identity,"
                "state,created) VALUES(?,?,?,?,?,?,'RECONCILING',?)",
                (
                    operation,
                    app_name,
                    source_key,
                    expected_version,
                    app.revision,
                    definition["source_identity"],
                    self.clock(),
                ),
            )
        try:
            # Authorization linearizes at accepted intent. Later revocation cannot undo an
            # already in-flight external mutation; no database lock spans source I/O.
            ref = app.source.write(source_key, content.encode("utf-8"), expected_version)
        except SourceConflict as error:
            self._record(operation, "FAILED", error)
            raise
        except Exception as error:
            self._record(operation, "RECONCILING", error)
            raise EffectUnknown(f"Write {operation} needs reconciliation") from error
        try:
            if not isinstance(ref, FileRef) or ref.key != source_key:
                raise EffectUnknown("Source returned an invalid write receipt")
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT revision,source_identity FROM app_state WHERE name=?", (app_name,)
                ).fetchone()
                if dict(current) != dict(definition):
                    raise EffectUnknown("App definition changed during source write")
                scheduled = self._schedule_receipt(
                    connection, app, source_key, expected_version, ref, self.clock()
                )
                connection.execute("UPDATE writes SET state='SUCCEEDED' WHERE id=?", (operation,))
            return {
                "operation_id": operation,
                "source_key": ref.key,
                "version": ref.version,
                "state": "SUCCEEDED",
                "indexing": "QUEUED" if scheduled else "SUPERSEDED",
            }
        except Exception as error:
            self._record(operation, "RECONCILING", error)
            raise EffectUnknown(f"Write {operation} needs reconciliation") from error

    @staticmethod
    def _authorize(connection, app, source_key, principal, expected_version):
        source = connection.execute(
            "SELECT * FROM source_refs WHERE app=? AND key=?", (app, source_key)
        ).fetchone()
        if source is None or source["deleted"] or source["version"] != expected_version:
            raise SourceConflict("Source version changed")
        documents = connection.execute(
            "SELECT * FROM documents WHERE app=? AND source_key=? AND state='ACTIVE'",
            (app, source_key),
        ).fetchall()
        if not documents or any(
            not principal.matches(json.loads(row["writers"])) for row in documents
        ):
            raise PermissionError(
                "Source replacement requires write permission on every affected document"
            )

    def _record(self, operation, state, error):
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE writes SET state=?,error=? WHERE id=?", (state, str(error), operation)
            )

    @staticmethod
    def _schedule_receipt(connection, app, source_key, expected_version, ref, now):
        """A confirmed historical effect does not supersede a newer observed source intent."""
        desired = connection.execute(
            "SELECT version,deleted FROM source_refs WHERE app=? AND key=?", (app.name, source_key)
        ).fetchone()
        if (
            desired is None
            or desired["deleted"]
            or desired["version"] not in {expected_version, ref.version}
        ):
            return False
        enqueue(connection, app, Change(ref), now)
        return True

    def reconcile(self, operation_id, outcome, ref=None):
        """Trusted reconciliation receipt; uncertain effects must be investigated externally."""
        if outcome not in {"applied", "not_applied", "failed"}:
            raise ValueError("Expected applied, not_applied, or failed")
        with self.database.transaction() as connection:
            operation = connection.execute(
                "SELECT * FROM writes WHERE id=?", (operation_id,)
            ).fetchone()
            if operation is None or operation["state"] != "RECONCILING":
                raise ValueError("Write is not awaiting reconciliation")
            if outcome == "applied":
                if not isinstance(ref, FileRef) or ref.key != operation["source_key"]:
                    raise ValueError("Applied writes require an exact source receipt")
                current = connection.execute(
                    "SELECT revision,source_identity FROM app_state WHERE name=?",
                    (operation["app"],),
                ).fetchone()
                if (
                    operation["revision"] != current["revision"]
                    or operation["source_identity"] != current["source_identity"]
                ):
                    raise ValueError(
                        "Cannot publish write receipt under a different app definition"
                    )
                self._schedule_receipt(
                    connection,
                    self.apps[operation["app"]],
                    operation["source_key"],
                    operation["expected_version"],
                    ref,
                    self.clock(),
                )
            connection.execute(
                "UPDATE writes SET state=?,error=NULL WHERE id=?",
                ("SUCCEEDED" if outcome == "applied" else "FAILED", operation_id),
            )
