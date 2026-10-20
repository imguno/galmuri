"""Boundary test collaborator; stores no transport-specific behavior."""

from types import SimpleNamespace


class FakeRuntime:
    def __init__(self):
        self.apps = {
            "readonly": SimpleNamespace(writable=False, description="Public guides"),
            "editable": SimpleNamespace(writable=True, description="Team documents"),
        }
        self.last_principal = None

    def search(self, app, query, principal, limit=20):
        self.last_principal = principal
        return [{"key": "guide", "text": f"Result: {query}", "version": "v1"}][:limit]

    def read(self, app, key, principal):
        self.last_principal = principal
        if key == "private":
            raise PermissionError("private internals")
        if key == "explode":
            raise RuntimeError("secret database credentials")
        return {"key": key, "text": "Hello", "version": "v1"}

    def write(self, app, key, content, principal, expected_version):
        self.last_principal = principal
        return {"key": key, "version": "v2", "content": content}

    def describe(self, app, principal):
        return {"name": app, "guides": ["Use search to discover documents."]}

    def status(self, app=None):
        return {"apps": list(self.apps), "state": "ACTIVE", "app": app}

    def sync(self, app=None):
        return {"state": "SUCCEEDED"}

    def collect(self, app, force=False):
        return {"collected": 1}

    def pause(self, app):
        return {"state": "PAUSED"}

    def resume(self, app):
        return {"state": "ACTIVE"}

    def retry(self, job_id):
        return {"state": "READY"}

    def cancel(self, job_id):
        return {"state": "CANCELLED"}

    def claim(self, worker_id, supported_apps=None):
        self.supported_apps = supported_apps
        return {"id": "job-1", "token": "lease-token"}

    def complete(self, claim, result):
        self.completed = result
        return True

    def heartbeat(self, claim):
        return True

    def fail(self, claim, error):
        self.failure = error

    def reconcile(self, job_id, outcome):
        self.reconciled = (job_id, outcome)

    def reconcile_write(self, operation_id, outcome, ref=None):
        self.reconciled_write = (operation_id, outcome, ref)
