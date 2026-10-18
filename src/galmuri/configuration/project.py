"""Load app objects in a project-specific module namespace."""

import hashlib
import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from galmuri.apps.definition import App
from galmuri.apps.resolution import resolve_apps
from galmuri.configuration.identity import caller, directory
from galmuri.configuration.storage import project_backends
from galmuri.configuration.tokens import load_or_create_token
from galmuri.contracts.documents import Principal
from galmuri.ingestion.permissions import DefaultPermissions


@dataclass(frozen=True)
class Project:
    root: Path
    apps: tuple[App, ...]
    database: Path
    principal: Principal
    exposures: dict[str, dict[str, Any]]
    adapters: dict[str, Any]
    cleanup_stores: tuple[Any, ...] = ()
    default_permissions: DefaultPermissions = DefaultPermissions()
    identity: object | None = None
    backend: object | None = None

    def runtime(self, *, activate: bool = False):
        from galmuri.runtime import Runtime

        return Runtime(
            self.database,
            self.apps,
            activate=activate,
            cleanup_stores=self.cleanup_stores,
            default_permissions=self.default_permissions,
            backend=self.backend,
        )

    def caller(self):
        return caller(self.identity, self.principal)

    def authenticator(self):
        if self.identity is not None:
            from galmuri.exposure.auth.accounts import AccountAuthenticator

            return AccountAuthenticator(self.identity, allow_anonymous=True)
        from galmuri.exposure.auth import TokenAuthenticator

        return TokenAuthenticator({self.token(): self.principal})

    def token(self) -> str:
        return load_or_create_token(self.root / ".runtime" / "admin.token")


def load_project(root: str | Path) -> Project:
    root = Path(root).resolve()
    namespace = "_workspace_" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if namespace not in sys.modules:
        package = types.ModuleType(namespace)
        package.__path__ = [str(root)]
        sys.modules[namespace] = package
    importlib.invalidate_caches()
    settings = importlib.import_module(f"{namespace}.config.settings")
    apps = []
    for reference in settings.APPS:
        if isinstance(reference, App):
            apps.append(reference)
            continue
        module, separator, attribute = reference.partition(":")
        if not separator:
            raise ValueError("App references use module.path:object_name")
        apps.append(getattr(importlib.import_module(f"{namespace}.{module}"), attribute))
    if len({app.name for app in apps}) != len(apps):
        raise ValueError("App names must be unique")
    database, routed, _ = project_backends(settings, root, apps)
    backends = list({id(value): value for value in routed.values()}.values())
    if len(backends) > 1:
        from galmuri.execution.routing.backend import RoutedBackend

        backend = RoutedBackend(routed)
    else:
        backend = backends[0] if backends else None
    default_store = getattr(backend, "default_store", None)
    principal = getattr(settings, "LOCAL_PRINCIPAL", Principal())
    permissions = DefaultPermissions.from_settings(getattr(settings, "DEFAULT_PERMISSIONS", None))
    return Project(
        root,
        resolve_apps(apps, database, permissions, default_store),
        database,
        principal,
        getattr(settings, "EXPOSURES", {}),
        getattr(settings, "EXPOSURE_ADAPTERS", {}),
        tuple(getattr(settings, "RETRIEVAL_CLEANUP_STORES", ())),
        permissions,
        directory(settings, root),
        backend,
    )
