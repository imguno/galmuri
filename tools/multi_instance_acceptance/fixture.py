"""Process-independent source and explicit deterministic embedding collaborators."""

import json
import os
from pathlib import Path

from galmuri import App, Change, ChangeSet, Document, File, FileRef, IngestResult
from galmuri.collection.policies import SyncPolicy
from galmuri.contracts.files import SourceConflict
from galmuri.execution.persistence.postgres import PostgresBackend
from galmuri.retrieval import EmbeddingSpec, RetrievalConfig
from galmuri.runtime import Runtime


class Source:
    def __init__(self, path):
        self.path = Path(path)
        self.identity = "process-fixture:" + self.path.as_posix()

    def _state(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def current(self, key):
        value = self._state()[key]
        return FileRef(key, value["version"], {"name": key + ".txt"})

    def changes(self, checkpoint):
        return ChangeSet(tuple(Change(self.current(key)) for key in sorted(self._state())))

    def read(self, ref):
        value = self._state()[ref.key]
        if value["version"] != ref.version:
            raise SourceConflict("Fixture source changed before read")
        return File(ref, value["text"].encode())


class Embedding:
    spec = EmbeddingSpec("test-only", "deterministic-two-dimensions", 2, "1")

    def embed_documents(self, texts):
        return tuple((1.0, 0.1) for _ in texts)

    def embed_query(self, text):
        return (1.0, 0.1)


def ingest(file):
    return IngestResult((Document(file.ref.key, file.text, readers=("*",)),))


def runtime(configuration):
    backend = PostgresBackend(os.environ["FRAMEWORK_POSTGRES_DSN"], schema=configuration["schema"])
    app = App(
        "sample",
        Source(configuration["source"]),
        ingest,
        policy=SyncPolicy(lease_seconds=configuration.get("lease_seconds", 30), retry_delay=0),
        retrieval=RetrievalConfig(Embedding(), backend.default_store(), retry_delay=0),
    )
    return Runtime("unused.sqlite", [app], backend=backend)


def publish(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)
