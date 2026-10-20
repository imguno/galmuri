"""Parser identity, data boundaries, and old import compatibility."""

import pytest

from galmuri import Document, File, FileRef
from galmuri.ingestion import IngestConfig, IngestHandler
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto as compatibility_auto
from galmuri.ingestion.parsers.markdown import parse_markdown as compatibility_markdown
from galmuri.ingestion.preparation import prepare_documents
from galmuri.parsing import ParsingConfig, parse_auto, parse_markdown, parse_python


def test_old_imports_are_the_same_canonical_functions():
    assert compatibility_auto is parse_auto
    assert compatibility_markdown is parse_markdown
    assert index_default is prepare_documents
    document = parse_auto(File(FileRef("id", "1", {"name": "GUIDE.MD"}), b"# Heading"))[0]
    assert document.metadata["headings"] == [{"level": 1, "text": "Heading"}]


def test_callable_instance_requires_explicit_identity():
    class Parser:
        def __call__(self, file):
            return (Document("doc", file.text),)

    with pytest.raises(ValueError, match="explicit parser identity"):
        ParsingConfig(Parser())
    parser = ParsingConfig(Parser(), identity="my-parser", revision="2")
    assert (
        parser.fingerprint
        == ParsingConfig(Parser(), identity="my-parser", revision="2").fingerprint
    )
    assert (
        parser.fingerprint
        != ParsingConfig(Parser(), identity="my-parser", revision="3").fingerprint
    )
    with pytest.raises(ValueError, match="explicit parser identity"):
        ParsingConfig(lambda file: ())


def test_handler_separates_parse_snapshot_and_grant_preparation():
    metadata = {"labels": ["before"]}

    def parser(file):
        return (Document("doc", file.text, metadata, readers=("*",)),)

    handler = IngestHandler(
        ParsingConfig(parser), IngestConfig(readers=("user:owner",), writers=())
    )
    documents = handler.parse(File(FileRef("source", "1"), b"text"))
    metadata["labels"].append("after")
    assert documents[0].metadata["labels"] == ["before"]
    assert documents[0].readers == ("*",)
    assert handler.prepare(documents).documents[0].readers == ("user:owner",)


def test_invalid_parser_documents_fail_at_the_parser_contract():
    handler = IngestHandler(
        ParsingConfig(lambda file: ({"text": "unsupported"},), identity="invalid"),
        IngestConfig(readers=(), writers=()),
    )
    with pytest.raises(TypeError, match="DocumentContract"):
        handler.parse(File(FileRef("source", "1"), b"text"))


def test_python_parser_never_executes_source(tmp_path):
    target = tmp_path / "must-not-exist"
    code = f"open({str(target)!r}, 'w').write('executed')\ndef greet():\n    pass\n"
    document = parse_python(File(FileRef("file.py", "1"), code.encode()))[0]
    assert not target.exists()
    assert document.metadata["symbols"][0]["name"] == "greet"
