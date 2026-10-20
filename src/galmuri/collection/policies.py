"""Default app workflow, replaceable without changing runtime scheduling."""

import math
from collections.abc import Callable
from dataclasses import dataclass

from galmuri.contracts.files import Change, ChangeSet, File, FileRef, SourceConflict
from galmuri.contracts.results import IngestResult


@dataclass(frozen=True)
class SyncPolicy:
    mode: str = "auto"
    interval: float = 60
    max_attempts: int = 3
    retry_delay: float = 1
    lease_seconds: float = 30

    def __post_init__(self) -> None:
        if self.mode not in {"auto", "changes", "scan"}:
            raise ValueError("Collection mode must be auto, changes, or scan")
        for name in ("interval", "lease_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.retry_delay) or self.retry_delay < 0:
            raise ValueError("retry_delay must be finite and nonnegative")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")

    def _mode(self, source: object) -> str:
        if self.mode == "auto":
            return "changes" if callable(getattr(source, "changes", None)) else "scan"
        return self.mode

    def validate(self, source: object) -> None:
        if not callable(getattr(source, "read", None)):
            raise TypeError("The app source must support read(ref)")
        mode = self._mode(source)
        if not callable(getattr(source, mode, None)):
            raise TypeError(f"Collection mode {mode!r} is not supported by this source")

    def discover(self, source: object, checkpoint: str | None) -> ChangeSet:
        self.validate(source)
        if self._mode(source) == "changes":
            result = source.changes(checkpoint)
            if not isinstance(result, ChangeSet):
                raise TypeError("Source changes() must return ChangeSet")
            if result.checkpoint is not None and not isinstance(result.checkpoint, str):
                raise TypeError("Source checkpoints must be strings or None")
            if not isinstance(result.complete, bool) or not all(
                isinstance(change, Change) and isinstance(change.ref, FileRef)
                for change in result.changes
            ):
                raise TypeError("Source changes() returned invalid change values")
            return result
        references = tuple(source.scan())
        if not all(isinstance(ref, FileRef) for ref in references):
            raise TypeError("Source scan() must return FileRef values")
        # A full scan requests processing of every listed file. A generic source
        # cannot prove deletion solely from a file missing in this listing.
        return ChangeSet(tuple(Change(ref) for ref in references), checkpoint)

    def execute(
        self, source: object, ref: FileRef, handler: Callable[[File], IngestResult]
    ) -> IngestResult:
        file = source.read(ref)
        if not isinstance(file, File):
            raise TypeError("Source read() must return File")
        if file.ref.key != ref.key or file.ref.version != ref.version:
            raise SourceConflict("Source read returned a different identity or version")
        result = handler(file)
        if not isinstance(result, IngestResult):
            raise TypeError("The app handler must return IngestResult")
        return result
