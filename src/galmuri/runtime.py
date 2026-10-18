"""Composition facade: lifecycle rules stay in their owning capabilities."""

import time
from collections.abc import Sequence
from pathlib import Path

from galmuri.apps.definition import App
from galmuri.apps.resolution import resolve_apps
from galmuri.apps.storage import DatabaseConfig
from galmuri.contracts.files import EffectUnknown, SourceConflict
from galmuri.execution.persistence.backend import SQLiteBackend
from galmuri.execution.ports import RuntimeBackend
from galmuri.execution.worker import work_once


class Runtime:
    def __init__(
        self,
        database: str | Path,
        apps: Sequence[App],
        clock=time.time,
        *,
        backend: RuntimeBackend | None = None,
        activate: bool = False,
        cleanup_stores: Sequence[object] = (),
        default_permissions=None,
    ):
        if backend is None and any(app.database != DatabaseConfig() for app in apps):
            raise ValueError("App database/namespace selection requires a configured backend")
        default_store = getattr(backend, "default_store", None)
        apps = resolve_apps(
            apps, database, default_permissions, default_store if callable(default_store) else None
        )
        self.apps = {app.name: app for app in apps}
        if len(self.apps) != len(apps):
            raise ValueError("App names must be unique")
        self.clock = clock
        components = (backend or SQLiteBackend(database)).open(self.apps, clock, activate=activate)
        self.database = components.database
        self.queue = components.queue
        self.discovery = components.discovery
        self.documents = components.documents
        self.queries = components.queries
        self.writes = components.writes
        self.state = components.state
        self.indexing = components.indexing
        self.ingestion = getattr(components, "ingestion", None)
        self._prefer_index = False
        if self.indexing is None and any(app.retrieval is not None for app in apps):
            raise ValueError("The selected backend does not provide a semantic indexing port")
        if cleanup_stores:
            register = getattr(self.indexing, "register_cleanup_store", None)
            if not callable(register):
                raise ValueError("The selected backend does not support cleanup store registration")
            for store in cleanup_stores:
                register(store)

    def collect(self, app_name, force=False):
        return self.discovery.collect(app_name, force)

    def claim(self, worker_id="local", supported_apps=None):
        return self.queue.claim(worker_id, supported_apps)

    def _owned(self, claim):
        return self.state.owned(claim)

    def complete(self, claim, result):
        current = self._owned(claim)
        if current is None:
            return False
        # Never use worker-supplied source, app revision or ACL generation as the baseline.
        app = self.apps[current["app"]]
        if app.revision != current["revision"]:
            self.queue.fail(current, SourceConflict("App revision changed"))
            return False
        if not current["deleted"]:
            source_current = getattr(app.source, "current", None)
            if callable(source_current):
                try:
                    ref = source_current(current["source_key"])
                    if ref.version != current["version"]:
                        raise SourceConflict("Original changed before publication")
                except (SourceConflict, FileNotFoundError) as error:
                    self.queue.fail(current, error)
                    return False
        return self.documents.publish(current, result)

    def fail(self, claim, error):
        current = self._owned(claim)
        if current is not None:
            self.queue.fail(current, error, isinstance(error, EffectUnknown))

    def heartbeat(self, claim):
        return self.queue.heartbeat(claim["id"], claim["token"])

    def work_once(self, worker_id="local", supported_apps=None):
        if self._prefer_index and self._index_once(worker_id, supported_apps):
            self._prefer_index = False
            return True
        if work_once(self, worker_id, supported_apps):
            self._prefer_index = True
            return True
        if self._index_once(worker_id, supported_apps):
            self._prefer_index = False
            return True
        return False

    def _index_once(self, worker_id, supported_apps):
        if self.indexing is None:
            return False
        if supported_apps is None:
            return self.indexing.work_once(worker_id)
        return any(
            self.indexing.work_once(worker_id, name)
            for name in supported_apps
            if name in self.apps and self.apps[name].revision == supported_apps[name]
        )

    def drain(self, max_jobs=1000, app_name=None):
        count = 0
        eligible = {app_name: self.apps[app_name].revision} if app_name else None
        while count < max_jobs and self.work_once(supported_apps=eligible):
            count += 1
        return count

    def sync(self, app_name=None):
        names = [app_name] if app_name else list(self.apps)
        collections = {name: self.collect(name, force=True) for name in names}
        return {"collections": collections, "processed": self.drain(app_name=app_name)}

    def tick(self):
        collections = {}
        for name in self.apps:
            try:
                collections[name] = self.collect(name)
            except Exception as error:
                collections[name] = {"state": "RETRY_WAIT", "error": str(error)}
        return {"collections": collections, "processed": 0}

    def pause(self, app_name):
        self._pause(app_name, True)

    def resume(self, app_name):
        self._pause(app_name, False)

    def _pause(self, app_name, paused):
        self.apps[app_name]
        self.state.pause(app_name, paused)

    def retry(self, job_id):
        self.queue.command(job_id, "retry")

    def cancel(self, job_id):
        self.queue.command(job_id, "cancel")

    def reconcile(self, job_id, outcome):
        self.queue.reconcile(job_id, outcome)

    def reconcile_write(self, operation_id, outcome, ref=None):
        self.writes.reconcile(operation_id, outcome, ref)

    def status(self, app_name=None):
        result = self.state.status(app_name)
        if self.indexing is not None:
            result["indexing"] = self.indexing.status(app_name)
        if self.ingestion is not None:
            result["ingestion"] = self.ingestion.status(app_name)
        return result

    def search(self, app_name, query, principal, limit=20, mode=None):
        app = self.apps[app_name]
        if app.retrieval is not None:
            return self.indexing.search(app_name, query, principal, limit, mode)
        if mode not in {None, "lexical"}:
            raise ValueError("This app does not configure vector retrieval")
        return self.queries.search(app_name, query, principal, limit)

    def read(self, app_name, document_key, principal):
        self.apps[app_name]
        return self.queries.read(app_name, document_key, principal)

    def write(self, app_name, document_key, content, principal, expected_version):
        return self.writes.write(app_name, document_key, content, principal, expected_version)

    def describe(self, app_name, principal):
        from galmuri.apps.description import configuration, operations

        app = self.apps[app_name]
        state = self.status(app_name)
        guides = [
            {"name": path.name, "text": path.read_text(encoding="utf-8")} for path in app.guides
        ]
        return {
            "name": app.name,
            "description": app.description,
            "revision": app.revision,
            "capabilities": ["search", "read"] + (["write"] if app.writable else []),
            "search": (
                self.indexing.describe(app_name, principal)
                if app.retrieval is not None
                else self.queries.describe(app_name, principal)
            ),
            "guides": guides,
            "collection": [
                {key: row[key] for key in ("collection_state", "next_collection", "paused")}
                for row in state["apps"]
            ],
            "authorization": (
                "Current reader/writer grants control document access; verified root accounts "
                "bypass document grants while credential scopes/apps and source capabilities apply"
            ),
            "configuration": configuration(app),
            "operations": operations(app),
        }
