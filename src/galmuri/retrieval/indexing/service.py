"""Projection application port: orchestration without owning provider internals."""

from dataclasses import asdict

from galmuri.documents.lexical.search import LexicalIndex
from galmuri.retrieval.indexing import cleanup
from galmuri.retrieval.indexing.claims import claim
from galmuri.retrieval.indexing.execution import execute
from galmuri.retrieval.indexing.reconciliation import reconcile
from galmuri.retrieval.search.service import Search


class Indexing:
    def __init__(self, database, apps, clock):
        self.database, self.apps, self.clock = database, apps, clock
        self.queries = Search(database, apps)
        self.cleanup_stores = {}
        self._prefer_cleanup = False

    def register_cleanup_store(self, store):
        """Attach credentials for retired physical storage without activating old config."""
        if not isinstance(store.identity, str) or not store.identity:
            raise ValueError("Cleanup store requires a stable nonempty identity")
        if not callable(getattr(store, "delete", None)):
            raise TypeError("Cleanup store must implement delete(namespace, ids)")
        self.cleanup_stores[store.identity] = store

    def work_once(self, worker_id="index", app_name=None):
        self._app(app_name)
        reconcile(self.database, self.apps, self.clock, app_name)
        if self._prefer_cleanup:
            self._prefer_cleanup = False
            if self._cleanup_once(app_name):
                return True
        job = claim(self.database, self.apps, self.clock, worker_id, app_name)
        if job is not None:
            execute(self.database, self.apps[job["app"]], job, self.clock)
            self._prefer_cleanup = True
            return True
        return self._cleanup_once(app_name)

    def _cleanup_once(self, app_name):
        return cleanup.work_once(
            self.database, self.apps, self.clock, app_name, cleanup_stores=self.cleanup_stores
        )

    def reindex(self, app_name=None, *, request_id=None):
        self._app(app_name)
        return reconcile(
            self.database, self.apps, self.clock, app_name, rebuild=True, request_id=request_id
        )

    def _app(self, app_name):
        if app_name is not None and app_name not in self.apps:
            raise KeyError(app_name)

    def retry(self, job_id):
        with self.database.transaction() as connection:
            job = connection.execute(
                "SELECT * FROM semantic_builds WHERE id=?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            if job["state"] != "FAILED":
                raise ValueError("Only failed semantic jobs can be retried")
            connection.execute(
                "UPDATE semantic_builds SET state='READY',attempts=0,available=?,error=NULL,"
                "token=NULL,lease_until=NULL,updated=? WHERE id=?",
                (self.clock(), self.clock(), job_id),
            )

    def lookup(self, job_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM semantic_builds WHERE id=?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def status(self, app_name=None):
        self._app(app_name)
        reconcile(self.database, self.apps, self.clock, app_name)
        where, parameters = (" WHERE app=?", (app_name,)) if app_name else ("", ())
        with self.database.connection() as connection:
            jobs = [
                dict(row)
                for row in connection.execute(
                    "SELECT id,app,key,fingerprint,state,stage,attempts,available,"
                    "worker,lease_until,"
                    "error,created,updated FROM semantic_builds" + where + " ORDER BY created,id",
                    parameters,
                )
            ]
            configs = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM semantic_configs" + where + " ORDER BY app", parameters
                )
            ]
            cleanups = [
                dict(row)
                for row in connection.execute(
                    "SELECT build,app,state,attempts,error,available FROM semantic_cleanup" + where,
                    parameters,
                )
            ]
        return {"configs": configs, "jobs": jobs, "cleanup": cleanups}

    def search(self, app, query, principal, limit=20, mode=None):
        return self.queries.search(app, query, principal, limit, mode)

    def describe(self, app, principal):
        config = self.apps[app].retrieval
        return {
            "method": config.mode,
            "modes": ["lexical", "vector", "hybrid"],
            "embedding": asdict(config.embedding.spec),
            "fingerprint": config.fingerprint,
            "chunker": config.chunker.identity,
            "limit": {"default": 20, "maximum": 1000},
            "visible_documents": len(self.queries.visible(app, principal)),
            "publication": "Only current completed vector generations are searchable",
            "query_policy": config.search.describe(),
            "lexical": LexicalIndex.describe(),
            "hybrid": "App-configured rank fusion; see query_policy for the active policy",
        }
