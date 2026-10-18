"""Resolve App-owned defaults before coordinator or remote-worker construction."""

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from galmuri.apps.defaults import AUTO_RETRIEVAL, _AutomaticRetrieval, resolve_retrieval
from galmuri.apps.definition import App
from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.handler import IngestHandler
from galmuri.ingestion.permissions import DefaultPermissions
from galmuri.parsing import ParsingConfig
from galmuri.processing import Pipeline, process_default
from galmuri.retrieval.config import RetrievalConfig


@dataclass(frozen=True)
class AppResolution:
    base_revision: str
    effective_revision: str
    database: Path
    permissions: DefaultPermissions
    defaults: tuple[str, ...]
    retrieval: RetrievalConfig | None
    retrieval_requested: RetrievalConfig | _AutomaticRetrieval | None
    handler_explicit: bool
    handler: object
    process_requested: object


def resolve_app(
    app: App, database: str | Path, permissions=None, default_store=None, store_factory=None
) -> App:
    """Bind paths/policy without source IO, parser execution, or model inference.

    Explicit handlers keep lexical retrieval unless configured otherwise. A changed
    parser/ingestion identity changes the App revision; normal activation guards then
    fence old workers. Retrieval/store identity is managed by the separate index lifecycle.
    """
    if not isinstance(app, App):
        raise TypeError("Project apps must be App instances")
    database = Path(database).resolve()
    previous = app._resolution
    if permissions is None and isinstance(previous, AppResolution):
        permissions = previous.permissions
    permissions = DefaultPermissions.from_settings(permissions)
    base_revision = app.revision
    if isinstance(previous, AppResolution) and app.revision == previous.effective_revision:
        base_revision = previous.base_revision
    handler = app.handler
    if isinstance(previous, AppResolution) and handler is previous.handler:
        handler = previous.process_requested
    requested_process = handler
    pipeline = isinstance(handler, Pipeline)
    builtin = handler is None or isinstance(handler, IngestHandler) or handler is process_default
    defaults = []
    explicit_descriptor = isinstance(handler, IngestHandler) and (
        previous is None or getattr(previous, "handler_explicit", False)
    )
    if pipeline:
        handler = handler.bind(permissions, parser=app.parser, ingestion=app.ingestion)
        suffix = hashlib.sha256(handler.fingerprint.encode()).hexdigest()[:24]
        revision = f"{base_revision}@ingest:{suffix}"
    elif builtin:
        parsing = app.parser
        if parsing is None and explicit_descriptor:
            parsing = handler.parsing
        if parsing is None:
            parsing = ParsingConfig()
            defaults.append("parser")
        ingestion = app.ingestion
        if ingestion is None and explicit_descriptor:
            ingestion = handler.config
        if ingestion is None:
            ingestion = IngestConfig()
            defaults.append("ingestion")
        elif not isinstance(ingestion, IngestConfig):
            raise TypeError("App ingestion must be IngestConfig")
        if ingestion.readers is None:
            ingestion = replace(ingestion, readers=permissions.readers)
            defaults.append("readers")
        if ingestion.writers is None:
            ingestion = replace(ingestion, writers=permissions.writers)
            defaults.append("writers")
        handler = IngestHandler(parsing, ingestion)
        suffix = hashlib.sha256(handler.fingerprint.encode()).hexdigest()[:24]
        revision = f"{base_revision}@ingest:{suffix}"
    else:
        if app.parser is not None or app.ingestion is not None:
            raise ValueError(
                "parser/ingestion configure built-in ingestion; omit the custom handler"
            )
        revision = base_revision
    requested = app.retrieval
    if isinstance(previous, AppResolution) and requested is previous.retrieval:
        requested = previous.retrieval_requested
    automatic = requested is AUTO_RETRIEVAL
    retrieval = requested
    if automatic:
        automatic_index = (
            pipeline or requested_process is None or requested_process is process_default
        )
        retrieval = RetrievalConfig() if automatic_index else None
    if retrieval is not None:
        if retrieval.embedding is None and not automatic:
            defaults.append("retrieval.embedding")
        if retrieval.store is None:
            if not automatic:
                defaults.append("retrieval.store")
            if store_factory is not None:
                default_store = store_factory(app)
        if retrieval.mode is None and not automatic:
            defaults.append("retrieval.mode")
        retrieval = resolve_retrieval(database, default_store, config=retrieval)
        if automatic:
            defaults.append("retrieval")
    resolution = AppResolution(
        base_revision,
        revision,
        database,
        permissions,
        tuple(defaults),
        retrieval,
        requested,
        explicit_descriptor,
        handler,
        requested_process,
    )
    return replace(
        app,
        handler=handler,
        process=handler,
        retrieval=retrieval,
        revision=revision,
        _resolution=resolution,
    )


def resolve_apps(
    apps, database: str | Path, permissions=None, store_factory=None
) -> tuple[App, ...]:
    return tuple(
        resolve_app(app, database, permissions, store_factory=store_factory) for app in apps
    )
