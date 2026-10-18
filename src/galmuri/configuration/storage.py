"""Resolve named database connections independently of local model/cache paths."""

from collections.abc import Mapping
from pathlib import Path


def _postgres(configured, namespace=None):
    if set(configured) - {"ENGINE", "DSN", "SCHEMA", "NAMESPACE", "OPTIONS"}:
        raise ValueError("Unknown PostgreSQL database option")
    if "SCHEMA" in configured and "NAMESPACE" in configured:
        raise ValueError("Specify NAMESPACE or SCHEMA, not both")
    options = configured.get("OPTIONS", {})
    if not isinstance(options, Mapping) or set(options) - {
        "connect_timeout",
        "lock_timeout",
        "statement_timeout",
    }:
        raise ValueError("Invalid PostgreSQL timeout options")
    schema = namespace or configured.get("NAMESPACE", configured.get("SCHEMA", "public"))
    return configured["DSN"], schema, dict(options)


def _path(value, root):
    path = Path(value)
    return path if path.is_absolute() else root / path


def identity_database(configured, root):
    if not isinstance(configured, Mapping):
        from galmuri.storage.database import Database

        return Database(_path(configured, root))
    engine = configured.get("ENGINE", "sqlite")
    if engine == "postgresql":
        from galmuri.storage.postgres import PostgresDatabase

        dsn, schema, options = _postgres(configured)
        return PostgresDatabase(dsn, schema=schema, **options)
    if engine == "sqlite":
        if set(configured) - {"ENGINE", "NAME"}:
            raise ValueError("Unknown SQLite database option")
        return identity_database(configured["NAME"], root)
    raise ValueError("Unsupported database engine")


def runtime_backend(configured, root, namespace=None, *, default_location=None):
    """Database namespaces are backend capabilities; they are not local directory names."""
    if not isinstance(configured, Mapping):
        configured = {"ENGINE": "sqlite", "NAME": configured}
    engine = configured.get("ENGINE", "sqlite")
    if engine == "postgresql":
        from galmuri.execution.persistence.postgres import PostgresBackend

        dsn, schema, options = _postgres(configured, namespace)
        return PostgresBackend(dsn, schema=schema, **options)
    if engine == "sqlite":
        from galmuri.execution.persistence.backend import SQLiteBackend

        if set(configured) - {"ENGINE", "NAME"}:
            raise ValueError("Unknown SQLite database option")
        if namespace is not None:
            raise ValueError("SQLite does not support database namespaces; use a separate DB alias")
        path = _path(configured["NAME"], root)
        vector_path = None
        if default_location is not None and path.resolve() != default_location.resolve():
            vector_path = path.with_name(path.name + ".vectors.sqlite3")
        return SQLiteBackend(path, vector_path=vector_path)
    raise ValueError("Unsupported database engine")


def project_backends(settings, root, apps):
    declared = getattr(settings, "DATABASES", None)
    if declared is None:
        declared = {"default": getattr(settings, "DATABASE", root / ".runtime" / "state.sqlite")}
    if not isinstance(declared, Mapping) or "default" not in declared:
        raise ValueError("DATABASES requires a default database")
    local = getattr(settings, "RUNTIME_DIRECTORY", root / ".runtime")
    # This path selects local artifacts/model caches, never contains a remote DSN.
    location = _path(local, root) / "state.sqlite"
    default = declared["default"]
    if not isinstance(default, Mapping):
        location = _path(default, root)
    elif default.get("ENGINE", "sqlite") == "sqlite":
        location = _path(default["NAME"], root)
    instances, physical, routed = {}, {}, {}
    for app in apps:
        selection = app.database
        if selection.alias not in declared:
            raise ValueError(f"Unknown database alias for app {app.name}")
        key = selection.alias, selection.namespace
        if key not in instances:
            candidate = runtime_backend(
                declared[selection.alias], root, selection.namespace, default_location=location
            )
            instances[key] = physical.setdefault(candidate.identity, candidate)
        routed[app.name] = instances[key]
    return location, routed, default
