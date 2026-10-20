"""One named, synchronous operation with an explicit serializable boundary."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from galmuri.contracts.callables import callable_identity, callable_location

KINDS = frozenset({"file", "documents", "result"})


@dataclass(frozen=True)
class Step:
    name: str
    process: Callable
    accepts: str = "documents"
    returns: str = "documents"
    identity: str | None = None
    revision: str = "1"

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Step name must be a nonempty string")
        if self.accepts not in KINDS or self.returns not in KINDS:
            raise ValueError("Step boundaries must be file, documents, or result")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("Step revision must be a nonempty string")
        object.__setattr__(
            self, "identity", callable_identity(self.process, self.identity, name="step")
        )

    @property
    def fingerprint(self):
        implementation = callable_location(self.process)
        value = [
            self.name,
            self.accepts,
            self.returns,
            self.identity,
            self.revision,
            implementation,
        ]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()
