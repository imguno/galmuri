"""Parser selection and explicit invalidation identity, independent of source IO."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from galmuri.contracts.callables import callable_identity, callable_location
from galmuri.contracts.files import File


@dataclass(frozen=True)
class ParsingConfig:
    process: Callable[[File], object] | None = None
    identity: str | None = None
    revision: str = "1"

    def __post_init__(self):
        if self.process is None:
            from galmuri.parsing import parse_auto

            object.__setattr__(self, "process", parse_auto)
            if self.identity is None:
                object.__setattr__(self, "identity", "galmuri.parsing:auto")
        if not callable(self.process):
            raise TypeError("Parser must be callable")
        identity = callable_identity(self.process, self.identity, name="parser")
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("Parser revision must be a nonempty string")
        object.__setattr__(self, "identity", identity)

    @property
    def parser(self):
        """Compatibility access; new declarations use process=function_reference."""
        return self.process

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                [self.identity, self.revision, callable_location(self.process)], ensure_ascii=True
            ).encode()
        ).hexdigest()
