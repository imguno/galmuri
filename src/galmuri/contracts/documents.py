"""Default document values are optional; custom objects use a projection contract."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from galmuri.contracts.grants import valid_grants


@dataclass(frozen=True)
class Principal:
    subject: str = "anonymous"
    groups: frozenset[str] = frozenset()
    administrator: bool = False

    def matches(self, grants: tuple[str, ...] | list[str]) -> bool:
        if not valid_grants(grants):
            return False
        return (
            "*" in grants
            or f"user:{self.subject}" in grants
            or any(f"group:{group}" in grants for group in self.groups)
        )


@dataclass(frozen=True)
class Document:
    key: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    readers: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Document identity must be nonempty")


class DocumentContract(Protocol):
    def project(self, value: object) -> Document:
        """Translate an implementation-owned object into boundary values."""
        ...
