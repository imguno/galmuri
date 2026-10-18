"""Wiring is immutable and validates every public boundary before acceptance."""

from dataclasses import FrozenInstanceError, replace
from itertools import repeat

import pytest

from galmuri import Document, File, FileRef, IngestResult
from galmuri.processing import Pipeline, Step
from galmuri.processing.values import MAX_DOCUMENTS


def parse(file):
    return (Document("doc", file.text),)


def uppercase(documents):
    return tuple(replace(document, text=document.text.upper()) for document in documents)


def punctuation(documents):
    return tuple(replace(document, text=document.text + "!") for document in documents)


def file():
    return File(FileRef("sample.txt", "v1"), b"hello")


def test_default_then_preserves_order_and_automatic_finalizer():
    original = Pipeline.default()
    pipeline = original.then(Step("arbitrary", uppercase)).then(Step("another", punctuation))
    assert [step.name for step in original.steps] == ["parse", "prepare"]
    assert [step.name for step in pipeline.steps] == ["parse", "arbitrary", "another", "prepare"]
    result = pipeline(file())
    assert result.documents[0].text == "HELLO!"
    assert result.documents[0].readers == result.documents[0].writers == ("*",)
    with pytest.raises(FrozenInstanceError):
        pipeline._steps = ()


def test_explicit_pipeline_respects_declared_order():
    pipeline = Pipeline(
        Step("first", parse, "file", "documents"),
        Step("second", punctuation),
        Step("third", uppercase),
    )
    assert pipeline(file()).documents[0].text == "HELLO!"


@pytest.mark.parametrize(
    "steps, match",
    [
        ([Step("clean", uppercase)], "previous output is file"),
        ([Step("same", parse, "file", "documents"), Step("same", uppercase)], "unique"),
        ([Step("prepare", parse, "file", "documents")], "reserves"),
        ([Step("incomplete", lambda value: value, "file", "file", "file-step")], "finish"),
    ],
)
def test_invalid_order_or_names_are_rejected(steps, match):
    with pytest.raises(ValueError, match=match):
        Pipeline(*steps)


def test_result_is_terminal_and_keeps_custom_grants():
    def finish(value):
        return IngestResult((Document("private", value.text, readers=("user:alice",)),), ("ready",))

    pipeline = Pipeline(Step("finish", finish, "file", "result"))
    assert pipeline(file()).documents[0].readers == ("user:alice",)
    assert pipeline(file()).messages == ("ready",)
    with pytest.raises(ValueError, match="terminal"):
        pipeline.then(Step("rewrite", uppercase, "result", "documents"))


def test_pipeline_identity_tracks_functions_order_and_revision():
    first = Step("clean", uppercase, identity="clean")
    assert first.fingerprint != replace(first, process=punctuation).fingerprint
    assert first.fingerprint != replace(first, revision="2").fingerprint
    pipeline = Pipeline.default().then(first).then(Step("punctuate", punctuation))
    reordered = Pipeline.default().then(Step("punctuate", punctuation)).then(first)
    assert pipeline.fingerprint != reordered.fingerprint


def test_callable_instances_need_stable_explicit_identity():
    class Custom:
        def __call__(self, documents):
            return documents

    with pytest.raises(ValueError, match="identity"):
        Step("custom", Custom())
    with pytest.raises(ValueError, match="identity"):
        Step("custom", lambda documents: documents)
    assert Step("custom", Custom(), identity="custom-v1").fingerprint


def test_project_loader_namespace_does_not_change_portable_fingerprint():
    def one(documents):
        return documents

    def two(documents):
        return documents

    one.__module__, two.__module__ = (
        "_workspace_0123456789abcdef.views",
        "_workspace_fedcba9876543210.views",
    )
    one.__qualname__ = two.__qualname__ = "clean"
    assert Step("clean", one).fingerprint == Step("clean", two).fingerprint


@pytest.mark.parametrize(
    "output, match",
    [
        (("not a document",), "DocumentContract"),
        ((Document("doc", "text", metadata={"invalid": float("nan")}),), "Out of range"),
        ((Document("same", "one"), Document("same", "two")), "duplicate"),
        (repeat(Document("doc", "text")), "boundary limit"),
    ],
)
def test_invalid_document_outputs_do_not_cross_boundary(output, match):
    step = Step("parser", lambda value: output, "file", "documents", "test-parser")
    with pytest.raises((TypeError, ValueError), match=match):
        Pipeline(step)(file())
    assert MAX_DOCUMENTS == 10_000


def test_file_transforms_cannot_change_source_identity():
    def rename(value):
        return File(FileRef("different", value.ref.version), value.content)

    pipeline = Pipeline(
        Step("rename", rename, "file", "file"), Step("parse", parse, "file", "documents")
    )
    with pytest.raises(ValueError, match="accepted file identity"):
        pipeline(file())
