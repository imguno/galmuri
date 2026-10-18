"""Each ingestion stage and its retry checkpoint stay in its app's backend."""


class Ingestion:
    def __init__(self, registry):
        self.registry = registry

    def run(self, job, app):
        return self.registry.port(job["app"], "ingestion").run(job, app)

    def release_completed(self):
        for port in self.registry.ports("ingestion"):
            port.release_completed()

    def status(self, app_name=None):
        if app_name is not None:
            port = self.registry.apps[app_name].ingestion
            return port.status(app_name) if port is not None else []
        return [row for name in self.registry.apps for row in self.status(name)]
