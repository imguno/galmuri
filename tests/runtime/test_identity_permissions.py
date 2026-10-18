from dataclasses import replace

from galmuri import App, Document, IngestResult, Principal
from galmuri.runtime import Runtime
from galmuri.sources.local import ReadOnlyFiles
from tests.runtime.test_lifecycle import make_runtime


def publish(file):
    return IngestResult((Document("doc", file.text, readers=("*",)),))


def test_new_source_root_resets_old_acl_override_on_explicit_activation(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "file.md").write_text("first", encoding="utf-8")
    (second / "file.md").write_text("second", encoding="utf-8")
    app = App("docs", ReadOnlyFiles(first), publish)
    runtime = Runtime(tmp_path / "state.db", [app])
    runtime.sync()
    runtime.documents.set_permissions("docs", "doc", (), ())
    switched = replace(app, source=ReadOnlyFiles(second), revision="2")
    runtime = Runtime(runtime.database.path, [switched], activate=True)
    runtime.sync()
    assert runtime.read("docs", "doc", Principal())["text"] == "second"


def test_same_declared_source_revision_preserves_current_acl_override(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "file.md").write_text("content", encoding="utf-8")
    app = App("docs", ReadOnlyFiles(root), publish)
    runtime = Runtime(tmp_path / "state.db", [app])
    runtime.sync()
    runtime.documents.set_permissions("docs", "doc", (), ())
    runtime = Runtime(runtime.database.path, [replace(app, revision="2")], activate=True)
    runtime.sync()
    assert runtime.search("docs", "content", Principal()) == []


def test_unknown_source_identity_conservatively_resets_overrides_on_activation(tmp_path):
    runtime, source = make_runtime(tmp_path, publish)
    runtime.sync()
    runtime.documents.set_permissions("drive", "doc", (), ())
    app = replace(runtime.apps["drive"], revision="2")
    runtime = Runtime(runtime.database.path, [app], activate=True, clock=lambda: 100)
    runtime.sync()
    assert runtime.read("drive", "doc", Principal())["text"] == "hello world"
