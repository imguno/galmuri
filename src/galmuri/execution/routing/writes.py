"""Route source mutation intent and reconciliation to their owning backend."""


class Writes:
    def __init__(self, registry):
        self.registry = registry

    def write(self, app_name, document_key, content, principal, expected_version):
        return self.registry.port(app_name, "writes").write(
            app_name, document_key, content, principal, expected_version
        )

    def lookup(self, operation_id):
        try:
            return self.registry.locate("writes", operation_id).lookup(operation_id)
        except KeyError:
            return None

    def reconcile(self, operation_id, outcome, ref=None):
        return self.registry.locate("writes", operation_id).reconcile(operation_id, outcome, ref)
