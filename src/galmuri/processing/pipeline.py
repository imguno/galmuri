"""Small immutable linear pipelines; runtime owns scheduling and checkpoints."""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import ClassVar

from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.permissions import DefaultPermissions
from galmuri.ingestion.preparation import prepare_documents
from galmuri.parsing.configuration import ParsingConfig
from galmuri.processing.steps import Step
from galmuri.processing.values import snapshot


@dataclass(frozen=True)
class _Prepare:
    config: IngestConfig

    def __call__(self, documents):
        return prepare_documents(
            documents, readers=self.config.readers, writers=self.config.writers
        )


@dataclass(frozen=True, init=False)
class Pipeline:
    _steps: tuple[Step, ...]
    _parsing: ParsingConfig | None
    _ingestion: IngestConfig
    durable_ingestion: ClassVar[bool] = True

    def __init__(self, *steps):
        if not steps or any(not isinstance(step, Step) for step in steps):
            raise TypeError("Pipeline requires one or more Step instances")
        names = [step.name for step in steps]
        if len(set(names)) != len(names):
            raise ValueError("Pipeline step names must be unique")
        kind = "file"
        for step in steps:
            if kind == "result":
                raise ValueError("IngestResult is terminal; no steps can follow a result")
            if step.accepts != kind:
                raise ValueError(
                    f"Step {step.name!r} accepts {step.accepts}, previous output is {kind}"
                )
            kind = step.returns
        if kind not in {"documents", "result"}:
            raise ValueError("Pipeline must finish with documents or an IngestResult")
        if kind == "documents" and "prepare" in names:
            raise ValueError("The automatic preparation step reserves the name 'prepare'")
        object.__setattr__(self, "_steps", tuple(steps))
        object.__setattr__(self, "_parsing", None)
        object.__setattr__(self, "_ingestion", IngestConfig())

    @classmethod
    def default(cls, *, parser=None, ingestion=None):
        parsing = parser if isinstance(parser, ParsingConfig) else ParsingConfig(parser)
        if ingestion is not None and not isinstance(ingestion, IngestConfig):
            raise TypeError("Pipeline ingestion must be an IngestConfig")
        pipeline = cls(
            Step(
                "parse",
                parsing.parser,
                accepts="file",
                returns="documents",
                identity=parsing.identity,
                revision=parsing.revision,
            )
        )
        object.__setattr__(pipeline, "_parsing", parsing)
        object.__setattr__(pipeline, "_ingestion", ingestion or IngestConfig())
        return pipeline

    def then(self, step):
        pipeline = Pipeline(*self._steps, step)
        object.__setattr__(pipeline, "_parsing", self._parsing)
        object.__setattr__(pipeline, "_ingestion", self._ingestion)
        return pipeline

    def bind(self, permissions=None, *, parser=None, ingestion=None):
        permissions = DefaultPermissions.from_settings(permissions)
        steps = self._steps
        if parser is not None:
            if self._parsing is None:
                raise ValueError("App parser config requires Pipeline.default()")
            parsing = parser if isinstance(parser, ParsingConfig) else ParsingConfig(parser)
            steps = (
                Step(
                    "parse", parsing.parser, "file", "documents", parsing.identity, parsing.revision
                ),
                *steps[1:],
            )
        config = ingestion or self._ingestion
        if not isinstance(config, IngestConfig):
            raise TypeError("Pipeline ingestion must be an IngestConfig")
        if self._steps[-1].returns == "result" and ingestion is not None:
            raise ValueError(
                "A pipeline returning IngestResult owns its grants; omit App ingestion"
            )
        config = replace(
            config,
            readers=permissions.readers if config.readers is None else config.readers,
            writers=permissions.writers if config.writers is None else config.writers,
        )
        pipeline = Pipeline(*steps)
        object.__setattr__(pipeline, "_parsing", self._parsing)
        object.__setattr__(pipeline, "_ingestion", config)
        return pipeline

    @property
    def steps(self):
        if self._steps[-1].returns == "result":
            return self._steps
        config = self._ingestion
        if config.readers is None or config.writers is None:
            permissions = DefaultPermissions.from_settings(None)
            config = replace(
                config,
                readers=permissions.readers if config.readers is None else config.readers,
                writers=permissions.writers if config.writers is None else config.writers,
            )
        return (
            *self._steps,
            Step(
                "prepare",
                _Prepare(config),
                "documents",
                "result",
                "galmuri.processing:prepare",
                config.fingerprint,
            ),
        )

    @property
    def fingerprint(self):
        return hashlib.sha256(
            json.dumps([step.fingerprint for step in self.steps]).encode()
        ).hexdigest()

    def __call__(self, file):
        value = snapshot("file", file)
        for step in self.steps:
            value = snapshot(step.returns, step.process(value))
            if step.returns == "file" and (
                value.ref.key != file.ref.key or value.ref.version != file.ref.version
            ):
                raise ValueError(
                    "File transforms must preserve the accepted file identity and version"
                )
        return value
