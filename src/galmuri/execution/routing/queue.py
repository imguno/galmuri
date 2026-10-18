"""Find a claim owner, then delegate transitions to that owner's queue."""

from .registry import RoundRobin


class Queue:
    def __init__(self, registry):
        self.registry, self.rotation = registry, RoundRobin()

    def claim(self, worker, supported_apps=None):
        for child in self.rotation.ordered(self.registry.children):
            eligible = {
                name: revision
                for name, revision in (supported_apps or {}).items()
                if self.registry.apps.get(name) is child
            }
            claim = child.queue.claim(worker, eligible if supported_apps is not None else None)
            if claim is not None:
                return claim
        return None

    def heartbeat(self, job_id, token):
        owners = []
        for child in self.registry.children:
            current = child.state.owned({"id": job_id, "token": token})
            if current is not None and self.registry.apps.get(current["app"]) is child:
                owners.append(child.queue)
        if len(owners) > 1:
            raise ValueError("Claim identifier is ambiguous across app databases")
        return owners[0].heartbeat(job_id, token) if owners else False

    def fail(self, job, error, unknown=False):
        return self.registry.port(job["app"], "queue").fail(job, error, unknown)

    def lookup(self, job_id):
        try:
            return self.registry.locate("queue", job_id).lookup(job_id)
        except KeyError:
            return None

    def command(self, job_id, command):
        return self.registry.locate("queue", job_id).command(job_id, command)

    def reconcile(self, job_id, outcome):
        return self.registry.locate("queue", job_id).reconcile(job_id, outcome)
