"""Resolve host credentials without accepting identity assertions from tool arguments."""

import os
from collections.abc import Mapping
from pathlib import Path

from galmuri.contracts.documents import Principal

from .storage import identity_database


def directory(settings, root):
    configured = getattr(settings, "IDENTITY_DATABASE", None)
    if configured is None:
        return None
    aliases = getattr(settings, "DATABASES", None)
    if aliases is None:
        aliases = {"default": getattr(settings, "DATABASE", root / ".runtime" / "state.sqlite")}
    if not isinstance(aliases, Mapping):
        raise ValueError("DATABASES must be a mapping of connection aliases")
    if isinstance(configured, str) and configured in aliases:
        configured = aliases[configured]
    from galmuri.identity import IdentityStore

    factory = getattr(settings, "IDENTITY_BACKEND", IdentityStore)
    if not callable(factory):
        raise TypeError("IDENTITY_BACKEND must be a directory factory")
    if factory is not IdentityStore and not isinstance(configured, Mapping):
        # Existing local directory factories retain their positional path contract.
        path = Path(configured)
        return factory(path if path.is_absolute() else root / path)
    return factory(database=identity_database(configured, root))


def caller(identity, fallback):
    if identity is None:
        return fallback
    value = os.environ.get("FRAMEWORK_TOKEN", "")
    filename = os.environ.get("FRAMEWORK_TOKEN_FILE")
    if filename:
        if value:
            raise ValueError("Use FRAMEWORK_TOKEN or FRAMEWORK_TOKEN_FILE, not both")
        with Path(filename).open("r", encoding="utf-8") as stream:
            value = stream.read(4097).strip()
    if len(value) > 4096:
        raise ValueError("Credential exceeds the maximum length")
    supplied = filename is not None or "FRAMEWORK_TOKEN" in os.environ
    return identity.authenticate(value) if supplied else Principal()
