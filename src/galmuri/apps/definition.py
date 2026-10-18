"""App connects implementations and owns policy selection."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from galmuri.apps.defaults import AUTO_RETRIEVAL, _AutomaticRetrieval
from galmuri.apps.storage import DatabaseConfig
from galmuri.contracts.files import ChangeSet, File, FileRef
from galmuri.contracts.results import IngestResult
from galmuri.ingestion.configuration import IngestConfig
from galmuri.parsing.configuration import ParsingConfig
from galmuri.retrieval.config import RetrievalConfig


class Workflow(Protocol):
    interval: float
    max_attempts: int
    retry_delay: float
    lease_seconds: float

    def validate(self, source: object) -> None: ...
    def discover(self, source: object, checkpoint: str | None) -> ChangeSet: ...
    def execute(
        self, source: object, ref: FileRef, handler: Callable[[File], IngestResult]
    ) -> IngestResult: ...


def _default_policy() -> Workflow:
    from galmuri.collection.policies import SyncPolicy

    return SyncPolicy()


@dataclass(frozen=True)
class App:
    name: str
    source: object
    handler: Callable[[File], IngestResult] | None = None
    policy: Workflow = field(default_factory=_default_policy)
    description: str = ""
    guides: tuple[Path, ...] = ()
    revision: str = "1"
    retrieval: RetrievalConfig | _AutomaticRetrieval | None = AUTO_RETRIEVAL
    parser: ParsingConfig | Callable[[File], object] | None = None
    ingestion: IngestConfig | None = None
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    process: Callable[[File], IngestResult] | None = field(default=None, kw_only=True)
    _bound_process: object | None = field(default=None, repr=False, compare=False, kw_only=True)
    _resolution: object | None = field(default=None, repr=False, compare=False, kw_only=True)

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("App name must be an alphanumeric identifier")
        handler, process = self.handler, self.process
        if handler is not process:
            previous = self._bound_process
            if handler is previous:
                selected = process
            elif process is previous:
                selected = handler
            else:
                raise ValueError(
                    "App process and legacy handler cannot select different implementations"
                )
        else:
            selected = handler
        object.__setattr__(self, "handler", selected)
        object.__setattr__(self, "process", selected)
        object.__setattr__(self, "_bound_process", selected)
        if selected is not None and not callable(selected):
            raise TypeError("App handler must be callable")
        if not isinstance(self.database, DatabaseConfig):
            raise TypeError("App database must be a DatabaseConfig instance")
        if self.parser is not None and not isinstance(self.parser, ParsingConfig):
            object.__setattr__(self, "parser", ParsingConfig(self.parser))
        if self.ingestion is not None and not isinstance(self.ingestion, IngestConfig):
            raise TypeError("App ingestion must be an IngestConfig instance")
        if self.retrieval is not AUTO_RETRIEVAL and self.retrieval is not None:
            if not isinstance(self.retrieval, RetrievalConfig):
                raise TypeError("App retrieval must be a RetrievalConfig instance or None")
        from galmuri.ingestion.sources import bind

        object.__setattr__(self, "source", bind(self.source))
        self.policy.validate(self.source)

    @property
    def writable(self) -> bool:
        return callable(getattr(self.source, "write", None))
