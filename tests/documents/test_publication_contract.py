"""Custom handler values cannot bypass the shared acceptance contract."""

import json

import pytest

from galmuri import App, Document, IngestResult, Principal
from galmuri.exposure.service import Service
from galmuri.runtime import Runtime
from tests.runtime.test_lifecycle import Source

from .helpers import table
from .test_lexical_publication import Backend


def runtime_with_result(database, tmp_path, value):
    source = Source()
    output = [value]

    def process(file):
        return output[0]

    runtime = Runtime(
        tmp_path / "unused.db",
        [App("docs", source, process=process, retrieval=None)],
        backend=Backend(database),
    )
    return runtime, source, output


@pytest.mark.parametrize(
    "document",
    [
        Document("doc", "needle", metadata={"value": float("nan")}, readers=("*",)),
        Document("doc", "needle", metadata={"value": float("inf")}, readers=("*",)),
        Document("doc", "needle", readers="user:alice*"),
        Document("doc", "needle", readers=("*",), writers="user:alice*"),
    ],
)
def test_invalid_custom_handler_output_fails_without_publishing(database, tmp_path, document):
    runtime, _, _ = runtime_with_result(database, tmp_path, IngestResult((document,)))
    runtime.sync()
    assert runtime.status()["jobs"][0]["state"] == "RETRY_WAIT"
    assert table(database, "documents") == []
    assert table(database, "lexical_postings") == []
    assert Service(runtime).call("search", {"app": "docs", "query": "needle"}, Principal()) == {
        "ok": True,
        "result": [],
    }


@pytest.mark.parametrize(
    "invalid",
    [
        Document("doc", "bad update", metadata={"bad": float("nan")}, readers=("*",)),
        Document("doc", "bad update", readers="user:alice*"),
    ],
)
def test_bad_update_preserves_last_accepted_body_and_cannot_publish_new_index(
    database, tmp_path, invalid
):
    valid = Document("doc", "accepted body", metadata={"safe": True}, readers=("*",))
    runtime, source, output = runtime_with_result(database, tmp_path, IngestResult((valid,)))
    runtime.sync()
    source.version = "2"
    output[0] = IngestResult((invalid,))
    runtime.sync()
    rows = table(database, "documents")
    assert len(rows) == 1
    assert (rows[0]["version"], rows[0]["text"]) == ("1", "accepted body")
    assert json.loads(rows[0]["metadata"]) == {"safe": True}
    assert json.loads(rows[0]["readers"]) == ["*"]
    assert next(job for job in runtime.status()["jobs"] if job["version"] == "2")["state"] == (
        "RETRY_WAIT"
    )
    assert runtime.search("docs", "bad update", Principal()) == []
    assert table(database, "lexical_postings") == []


def test_direct_completion_validates_snapshot_and_preserves_explicit_denial(database, tmp_path):
    runtime, _, _ = runtime_with_result(database, tmp_path, IngestResult(()))
    runtime.collect("docs")
    claim = runtime.claim()
    with pytest.raises(TypeError, match="Permissions"):
        runtime.complete(claim, IngestResult((Document("doc", "needle", readers="user:alice*"),)))
    assert table(database, "documents") == []
    metadata = {"labels": ["initial"]}
    document = Document("doc", "needle", metadata=metadata, readers=(), writers=())
    assert runtime.complete(claim, IngestResult((document,)))
    metadata["labels"].append("later mutation")
    accepted = table(database, "documents")[0]
    assert json.loads(accepted["metadata"]) == {"labels": ["initial"]}
    assert json.loads(accepted["readers"]) == []
    assert json.loads(accepted["writers"]) == []
    assert runtime.search("docs", "needle", Principal()) == []


@pytest.mark.parametrize("messages", ["not-a-message-list", (object(),)])
def test_invalid_diagnostics_cannot_partially_publish(database, tmp_path, messages):
    document = Document("doc", "needle", readers=("*",))
    runtime, _, _ = runtime_with_result(database, tmp_path, IngestResult((document,), messages))
    runtime.sync()
    assert runtime.status()["jobs"][0]["state"] == "RETRY_WAIT"
    assert table(database, "documents") == []


def test_remote_shared_service_rejects_the_same_malformed_values(database, tmp_path):
    runtime, _, _ = runtime_with_result(database, tmp_path, IngestResult(()))
    runtime.collect("docs")
    claim = runtime.claim()
    service = Service(runtime)
    operator = Principal("worker", administrator=True)
    for document in (
        {"key": "doc", "text": "needle", "readers": "user:alice*"},
        {"key": "doc", "text": "needle", "metadata": {"bad": float("nan")}, "readers": ["*"]},
    ):
        response = service.call(
            "worker.complete", {"claim": claim, "result": {"documents": [document]}}, operator
        )
        assert response["error"]["code"] == "invalid_request"
        assert table(database, "documents") == []
    response = service.call(
        "worker.complete",
        {"claim": claim, "result": {"documents": [{"key": "doc", "text": "needle"}]}},
        operator,
    )
    assert response == {"ok": True, "result": True}
    assert (
        service.call("read", {"app": "docs", "document_key": "doc"}, Principal())["error"]["code"]
        == "forbidden"
    )
