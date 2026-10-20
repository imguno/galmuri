"""App policy fallbacks are independent of callers and source credentials."""

from collections.abc import Mapping
from dataclasses import dataclass

from galmuri.ingestion.configuration import _grants


@dataclass(frozen=True)
class DefaultPermissions:
    readers: tuple[str, ...] = ("*",)
    writers: tuple[str, ...] = ("*",)

    def __post_init__(self):
        for name in ("readers", "writers"):
            value = _grants(getattr(self, name), name)
            if value is None:
                raise TypeError("Default permission grants must be explicit collections")
            object.__setattr__(self, name, value)

    @classmethod
    def from_settings(cls, value=None):
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping) or value.keys() - {"read", "write"}:
            raise ValueError("DEFAULT_PERMISSIONS accepts only read and write grant collections")
        return cls(value.get("read", ("*",)), value.get("write", ("*",)))
