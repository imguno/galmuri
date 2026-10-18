"""Publication and permission edits remain inside one app's transaction boundary."""


class Publication:
    def __init__(self, registry):
        self.registry = registry

    def publish(self, job, result):
        return self.registry.port(job["app"], "documents").publish(job, result)

    def set_permissions(self, app, key, readers, writers, expected_revision=None):
        return self.registry.port(app, "documents").set_permissions(
            app, key, readers, writers, expected_revision=expected_revision
        )
