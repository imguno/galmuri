"""Replacement backend contracts; implementations own coordinated lifecycle guarantees."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from galmuri.apps.definition import App
from galmuri.contracts.documents import Principal
from galmuri.contracts.files import FileRef
from galmuri.contracts.results import IngestResult

Claim = dict[str, Any]


class ExecutionPort(Protocol):
    def lookup(self, job_id: str) -> Claim | None: ...
    def claim(self, worker: str, supported_apps: dict[str, str] | None = None) -> Claim | None: ...
    def heartbeat(self, job_id: str, token: str) -> bool: ...
    def fail(self, job: Claim, error: Exception, unknown: bool = False) -> None: ...
    def command(self, job_id: str, command: str) -> None: ...
    def reconcile(self, job_id: str, outcome: str) -> None: ...


class DiscoveryPort(Protocol):
    def collect(self, name: str, force: bool = False) -> dict: ...


class PublicationPort(Protocol):
    def publish(self, job: Claim, result: IngestResult) -> bool: ...
    def set_permissions(
        self,
        app: str,
        key: str,
        readers: tuple[str, ...],
        writers: tuple[str, ...],
        expected_revision: int | None = None,
    ) -> int: ...


class QueryPort(Protocol):
    def list_documents(
        self,
        app: str,
        principal: Principal,
        *,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
        inventory: bool = False,
    ) -> dict: ...
    def read(self, app: str, key: str, principal: Principal) -> dict: ...
    def search(self, app: str, query: str, principal: Principal, limit: int = 20) -> list[dict]: ...
    def describe(self, app: str, principal: Principal) -> dict: ...


class WritePort(Protocol):
    def lookup(self, operation_id: str) -> dict | None: ...
    def write(
        self,
        app_name: str,
        document_key: str,
        content: str,
        principal: Principal,
        expected_version: str,
    ) -> dict: ...
    def reconcile(self, operation_id: str, outcome: str, ref: FileRef | None = None) -> None: ...


class StatePort(Protocol):
    def owned(self, claim: Claim) -> Claim | None: ...
    def pause(self, name: str, paused: bool) -> None: ...
    def status(self, app_name: str | None = None) -> dict: ...


class IndexingPort(Protocol):
    def lookup(self, job_id: str) -> Claim | None: ...
    def register_cleanup_store(self, store: object) -> None: ...
    def work_once(self, worker_id: str, app_name: str | None = None) -> bool: ...
    def reindex(self, app_name: str | None = None, *, request_id: str | None = None) -> dict: ...
    def status(self, app_name: str | None = None) -> dict: ...
    def retry(self, job_id: str) -> None: ...
    def search(
        self, app: str, query: str, principal: Principal, limit: int = 20, mode: str | None = None
    ) -> list[dict]: ...
    def describe(self, app: str, principal: Principal) -> dict: ...


class IngestionPort(Protocol):
    def run(self, job: Claim, app: App) -> IngestResult: ...
    def status(self, app_name: str | None = None) -> list[dict]: ...
    def release_completed(self) -> None: ...


@dataclass(frozen=True)
class RuntimeComponents:
    """A coherent backend bundle, not permission to mix incompatible transaction boundaries."""

    database: object
    queue: ExecutionPort
    discovery: DiscoveryPort
    documents: PublicationPort
    queries: QueryPort
    writes: WritePort
    state: StatePort
    indexing: IndexingPort | None = None
    ingestion: IngestionPort | None = None


class RuntimeBackend(Protocol):
    def open(
        self, apps: Mapping[str, App], clock: Callable[[], float], *, activate: bool = False
    ) -> RuntimeComponents: ...
