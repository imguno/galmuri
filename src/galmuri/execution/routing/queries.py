"""Document reads and discovery resolve exclusively through the named app."""


class Queries:
    def __init__(self, registry):
        self.registry = registry

    def read(self, app, key, principal):
        return self.registry.port(app, "queries").read(app, key, principal)

    def search(self, app, query, principal, limit=20):
        return self.registry.port(app, "queries").search(app, query, principal, limit)

    def describe(self, app, principal):
        return self.registry.port(app, "queries").describe(app, principal)

    def list_documents(self, app, principal, **options):
        return self.registry.port(app, "queries").list_documents(app, principal, **options)


class Discovery:
    def __init__(self, registry):
        self.registry = registry

    def collect(self, name, force=False):
        return self.registry.port(name, "discovery").collect(name, force)
