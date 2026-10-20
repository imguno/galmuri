"""Explicit host composition; protocol dependencies are loaded only when selected."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from galmuri.contracts.documents import Principal
from galmuri.exposure.auth.tokens import Authenticator
from galmuri.exposure.service import Service


class Adapter(Protocol):
    def run(self) -> None: ...


@dataclass(frozen=True)
class HostContext:
    principal: Principal
    authenticator: Authenticator


class AdapterRegistry:
    def __init__(self):
        self._factories: dict[str, Callable] = {}
        self._host_defaults: dict[str, Callable[[HostContext], dict]] = {}

    def register(self, name: str, factory: Callable, *, host_defaults=None) -> None:
        if name in self._factories:
            raise ValueError(f"Adapter already registered: {name}")
        self._factories[name] = factory
        if host_defaults is not None:
            self._host_defaults[name] = host_defaults

    def create(self, name: str, service: Service, **options) -> Adapter:
        try:
            factory = self._factories[name]
        except KeyError:
            raise ValueError(f"Unknown exposure adapter: {name}") from None
        return factory(service, **options)

    def compose(self, name: str, service: Service, context: HostContext, **options) -> Adapter:
        defaults = self._host_defaults.get(name)
        resolved = defaults(context) if defaults else {}
        return self.create(name, service, **(resolved | options))


def default_registry() -> AdapterRegistry:
    from galmuri.exposure.cli import CliAdapter
    from galmuri.exposure.grpc import GrpcAdapter
    from galmuri.exposure.http import HttpAdapter
    from galmuri.exposure.mcp import McpAdapter

    registry = AdapterRegistry()
    for name, factory in (
        ("http", HttpAdapter),
        ("mcp", McpAdapter),
        ("grpc", GrpcAdapter),
        ("cli", CliAdapter),
    ):
        defaults = (
            (lambda context: {"authenticator": context.authenticator})
            if name in {"http", "grpc"}
            else (lambda context: {"principal": context.principal})
        )
        registry.register(name, factory, host_defaults=defaults)
    return registry
