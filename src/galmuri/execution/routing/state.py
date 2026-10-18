"""Aggregate projections without pretending independent databases form one transaction."""

from .registry import projection


class State:
    def __init__(self, registry):
        self.registry = registry

    def owned(self, claim):
        matches = [
            current
            for child in self.registry.children
            if (current := child.state.owned(claim)) is not None
            and self.registry.apps.get(current["app"]) is child
        ]
        if len(matches) > 1:
            raise ValueError("Claim identifier is ambiguous across app databases")
        return matches[0] if matches else None

    def pause(self, name, paused):
        return self.registry.port(name, "state").pause(name, paused)

    def status(self, app_name=None):
        if app_name is not None:
            return self.registry.port(app_name, "state").status(app_name)
        return projection(
            [self.registry.port(name, "state").status(name) for name in self.registry.apps],
            ("apps", "jobs", "attempts", "events", "writes", "documents"),
        )
