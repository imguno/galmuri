"""Open each coherent backend once, then bind app names to its ports."""

from types import MappingProxyType

from galmuri.execution.ports import RuntimeComponents

from .indexing import Indexing
from .ingestion import Ingestion
from .publication import Publication
from .queries import Discovery, Queries
from .queue import Queue
from .registry import Registry
from .state import State
from .writes import Writes


class RoutedBackend:
    def __init__(self, backends):
        self.backends = dict(backends)

    def default_store(self, app):
        factory = getattr(self.backends[app.name], "default_store", None)
        return factory() if callable(factory) else None

    def open(self, apps, clock, *, activate=False):
        groups = {}
        for name, app in apps.items():
            backend = self.backends[name]
            identity = getattr(backend, "identity", id(backend))
            groups.setdefault(identity, (backend, {}))[1][name] = app
        children = {}
        for backend, definitions in groups.values():
            child = backend.open(definitions, clock, activate=activate)
            for name, app in definitions.items():
                if app.retrieval is not None and child.indexing is None:
                    raise ValueError(f"App {name!r} requires an indexing backend")
                children[name] = child
        registry = Registry(children)
        return RuntimeComponents(
            database=MappingProxyType({name: child.database for name, child in children.items()}),
            queue=Queue(registry),
            discovery=Discovery(registry),
            documents=Publication(registry),
            queries=Queries(registry),
            writes=Writes(registry),
            state=State(registry),
            indexing=Indexing(registry) if registry.ports("indexing") else None,
            ingestion=Ingestion(registry) if registry.ports("ingestion") else None,
        )
