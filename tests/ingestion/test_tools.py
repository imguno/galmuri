from dataclasses import dataclass

import pytest

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File, FileRef
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto, parse_markdown, parse_python, parse_text


def file(name, text, version="1"):
    return File(FileRef(name, version), text.encode("utf-8"))


def test_default_parser_retains_identity_and_denies_access_until_granted():
    documents = parse_text(file("notes.txt", "hello"))
    result = index_default(documents)
    assert result.documents[0].key == "notes.txt"
    assert result.documents[0].text == "hello"
    assert result.documents[0].metadata["source_version"] == "1"
    assert result.documents[0].readers == ()
    assert result.documents[0].writers == ()


def test_markdown_heading_metadata_ignores_fenced_code():
    result = parse_markdown(file("notes.md", "# Main\n```md\n# Example\n```\n## Detail\n"))[0]
    assert result.metadata["headings"] == [
        {"level": 1, "text": "Main"},
        {"level": 2, "text": "Detail"},
    ]
    assert result.metadata["format"] == "markdown"


def test_python_ast_is_never_executed_and_identity_is_stable_across_edits(tmp_path):
    marker = tmp_path / "executed"
    source = (
        f"open({str(marker)!r}, 'w').write('bad')\nclass Tool:\n    def run(self):\n        pass\n"
    )
    first = parse_python(file("source.py", source))[0]
    second = parse_python(file("source.py", "# a new comment\n" + source, "2"))[0]
    assert first.key == second.key == "source.py"
    assert not marker.exists()
    assert [item["name"] for item in first.metadata["symbols"]] == ["Tool", "Tool.run"]
    assert second.metadata["source_version"] == "2"


def test_invalid_python_and_binary_are_explicit_parser_failures():
    with pytest.raises(SyntaxError):
        parse_auto(file("broken.py", "def ="))
    with pytest.raises(ValueError, match="Binary"):
        parse_text(file("data.bin", "a\0b"))


def test_auto_selects_parser_without_user_dispatch():
    assert parse_auto(file("readme.MD", "# Title"))[0].metadata["format"] == "markdown"
    assert parse_auto(file("script.py", "x = 1"))[0].metadata["format"] == "python"
    assert parse_auto(file("log.txt", "entry"))[0].metadata["format"] == "text"


def test_custom_schema_projects_at_explicit_boundary_and_permissions_are_overridable():
    @dataclass
    class Note:
        slug: str
        body: str

    class NoteContract:
        def project(self, note):
            return Document(note.slug, note.body, {"custom": True}, ("group:dev",))

    result = index_default(
        [Note("note-1", "custom")],
        contract=NoteContract(),
        readers=["user:owner"],
        writers=["group:editors"],
    )
    assert result.documents == (
        Document("note-1", "custom", {"custom": True}, ("user:owner",), ("group:editors",)),
    )


def test_preparation_snapshots_metadata_instead_of_retaining_caller_owned_state():
    document = Document("id", "contents", {"tags": ["first"]}, ("group:dev",))
    result = index_default([document])
    document.metadata["tags"].append("second")
    assert result.documents[0].metadata["tags"] == ["first"]
    assert result.documents[0].readers == ("group:dev",)
    assert index_default([document], readers=[]).documents[0].readers == ()


def test_invalid_projection_duplicates_and_permission_types_are_rejected():
    with pytest.raises(TypeError, match="DocumentContract"):
        index_default([{"text": "custom"}])
    with pytest.raises(ValueError, match="duplicate"):
        index_default([Document("id", "a"), Document("id", "b")])
    with pytest.raises(TypeError, match="collection"):
        index_default([], readers="group:dev")
