"""Live principals retain credential identity, never caller-asserted groups."""

from .errors import AuthenticationError


class VerifiedPrincipal:
    __slots__ = ("_store", "_digest", "subject", "credential_id", "credential_kind")

    def __init__(self, store, digest, row):
        self._store, self._digest = store, digest
        self.subject = row["user_id"]
        self.credential_id, self.credential_kind = row["id"], row["kind"]

    def __repr__(self):
        return f"VerifiedPrincipal(subject={self.subject!r}, credential_id={self.credential_id!r})"

    def _current(self):
        try:
            return self._store._credential(self._digest)
        except AuthenticationError:
            return None

    @property
    def groups(self):
        current = self._current()
        return current["groups"] if current else frozenset()

    @property
    def administrator(self):
        current = self._current()
        return bool(current and current["administrator"] and "manage" in current["scopes"])

    @property
    def root(self):
        current = self._current()
        return bool(current and current["is_root"])

    @property
    def is_authenticated(self):
        return self._current() is not None

    def authorize(self, scope, app=None):
        current = self._current()
        return bool(
            current
            and scope in current["scopes"]
            and (app is None or "*" in current["apps"] or app in current["apps"])
        )

    def matches(self, grants):
        current = self._current()
        return bool(
            current
            and (
                current["is_root"]
                or "*" in grants
                or f"user:{self.subject}" in grants
                or any(f"group:{g}" in grants for g in current["groups"])
            )
        )
