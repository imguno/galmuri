"""Fair indexing requests across independent backend-owned job lifecycles."""

from .registry import RoundRobin, projection


class Indexing:
    def __init__(self, registry):
        self.registry, self.rotation = registry, RoundRobin()

    def register_cleanup_store(self, store):
        for port in self.registry.ports("indexing"):
            port.register_cleanup_store(store)

    def work_once(self, worker_id, app_name=None):
        if app_name is not None:
            port = self.registry.apps[app_name].indexing
            return port.work_once(worker_id, app_name) if port is not None else False
        return any(
            port.work_once(worker_id)
            for port in self.rotation.ordered(self.registry.ports("indexing"))
        )

    def reindex(self, app_name=None, *, request_id=None):
        options = {"request_id": request_id} if request_id is not None else {}
        if app_name is not None:
            return self.registry.port(app_name, "indexing").reindex(app_name, **options)
        results = [port.reindex(**options) for port in self.registry.ports("indexing")]
        return {
            "scheduled": sum(result["scheduled"] for result in results),
            "jobs": [job for result in results for job in result["jobs"]],
        }

    def status(self, app_name=None):
        if app_name is not None:
            port = self.registry.apps[app_name].indexing
            return (
                port.status(app_name)
                if port is not None
                else {"configs": [], "jobs": [], "cleanup": []}
            )
        return projection(
            [self.status(name) for name in self.registry.apps],
            ("configs", "jobs", "cleanup"),
        )

    def lookup(self, job_id):
        try:
            return self.registry.locate("indexing", job_id).lookup(job_id)
        except KeyError:
            return None

    def retry(self, job_id):
        return self.registry.locate("indexing", job_id).retry(job_id)

    def search(self, app, query, principal, limit=20, mode=None):
        return self.registry.port(app, "indexing").search(app, query, principal, limit, mode)

    def describe(self, app, principal):
        return self.registry.port(app, "indexing").describe(app, principal)
