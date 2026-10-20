"""Real publication acceptance, stale work, and restart behavior for both backends."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from galmuri import App, Change, ChangeSet, Document, File, FileRef, IngestResult, Principal
from galmuri.documents import publication
from galmuri.documents.lexical import migration
from galmuri.execution.persistence.composition import open_relational
from galmuri.runtime import Runtime

from .helpers import publish, table


class Source:
    version = "1"
    deleted = False

    def changes(self, checkpoint):
        return ChangeSet((Change(FileRef("source", self.version), deleted=self.deleted),))

    def read(self, ref):
        return File(ref, b"source body")


class Backend:
    def __init__(self, database):
        self.database = database

    def open(self, apps, clock, *, activate=False):
        return open_relational(self.database, apps, clock, activate=activate)


def setup_runtime(database, tmp_path):
    source = Source()
    runtime = Runtime(
        tmp_path / "unused.db",
        [App("docs", source, retrieval=None)],
        clock=lambda: 100,
        backend=Backend(database),
    )
    return runtime, source


def result(text):
    return IngestResult((Document("doc", text, readers=("*",)),))


def test_accepted_intent_retires_index_and_late_result_cannot_restore_it(database, tmp_path):
    runtime, source = setup_runtime(database, tmp_path)
    runtime.collect("docs")
    first = runtime.claim()
    assert runtime.complete(first, result("original"))
    assert runtime.search("docs", "original", Principal())[0]["key"] == "doc"
    source.version = "2"
    runtime.collect("docs", force=True)
    assert table(database, "lexical_postings") == []
    assert runtime.search("docs", "original", Principal()) == []
    second = runtime.claim()
    source.version = "3"
    runtime.collect("docs", force=True)
    assert not runtime.complete(second, result("stale"))
    assert table(database, "lexical_postings") == []
    assert runtime.complete(runtime.claim(), result("current"))
    assert runtime.search("docs", "current", Principal())[0]["version"] == "3"
    source.version = "4"
    source.deleted = True
    runtime.collect("docs", force=True)
    assert runtime.search("docs", "current", Principal()) == []
    assert table(database, "lexical_postings") == []
    assert table(database, "lexical_corpora")[0]["document_count"] == 0


def test_index_failure_rolls_back_acceptance_and_can_retry_same_claim(
    database, tmp_path, monkeypatch
):
    runtime, _ = setup_runtime(database, tmp_path)
    runtime.collect("docs")
    claim = runtime.claim()
    original = publication.index_document

    def failing(*args):
        original(*args)
        raise RuntimeError("index storage failure")

    monkeypatch.setattr(publication, "index_document", failing)
    with pytest.raises(RuntimeError, match="index storage"):
        runtime.complete(claim, result("pending"))
    for name in ("documents", "lexical_documents", "lexical_postings", "lexical_terms"):
        assert table(database, name) == []
    assert runtime.queue.lookup(claim["id"])["state"] == "RUNNING"
    monkeypatch.setattr(publication, "index_document", original)
    assert runtime.complete(claim, result("accepted"))
    assert runtime.queue.lookup(claim["id"])["state"] == "SUCCEEDED"
    assert table(database, "lexical_corpora")[0]["document_count"] == 1


def test_concurrent_upgrade_does_not_duplicate_postings_or_corpus_counts(database):
    with database.transaction() as connection:
        publish(connection, "old", "existing old document", indexed=False)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: migration.initialize(database), range(2)))
    assert table(database, "lexical_corpora") == [
        {"app": "docs", "document_count": 1, "total_length": 3}
    ]
    assert len(table(database, "lexical_postings")) == 3


def test_app_activation_retires_postings_and_rejects_stale_runtime(database, tmp_path):
    runtime, source = setup_runtime(database, tmp_path)
    runtime.collect("docs")
    assert runtime.complete(runtime.claim(), result("before"))
    newer = Runtime(
        tmp_path / "unused.db",
        [App("docs", source, retrieval=None, revision="2")],
        clock=lambda: 100,
        backend=Backend(database),
        activate=True,
    )
    assert table(database, "lexical_postings") == []
    with pytest.raises(ValueError, match="revision"):
        runtime.search("docs", "before", Principal())
    newer.collect("docs")
    assert newer.complete(newer.claim(), result("after"))
    assert newer.search("docs", "after", Principal())[0]["key"] == "doc"
    with pytest.raises(ValueError, match="revision"):
        runtime.search("docs", "after", Principal())
