"""Project and app generation are separate, import-free development operations."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from galmuri.cli import main
from galmuri.configuration import load_project
from galmuri.scaffolding import create_app, create_project, generation, start_project


def _run(root, *arguments):
    result = subprocess.run(
        [sys.executable, *arguments], cwd=root, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_startproject_creates_configuration_without_any_app(tmp_path):
    _run(tmp_path, "-m", "galmuri", "startproject", "example")
    root = tmp_path / "example"
    assert (root / "manage.py").is_file()
    assert (root / "config/settings.py").is_file()
    assert [path.name for path in (root / "apps").iterdir()] == ["__init__.py"]
    assert "APPS = []" in (root / "config/settings.py").read_text(encoding="utf-8")
    assert json.loads((root / ".project.json").read_text())["state"] == "COMPLETE"
    assert not (root / ".runtime").exists()


def test_manage_startapp_never_imports_settings_or_composes_a_runtime(tmp_path):
    root = start_project("example", tmp_path / "example")
    # Both packages are executable user code. Generation only checks their paths.
    code = "raise AssertionError('generation imported user code')\n"
    for relative in ("config/__init__.py", "config/settings.py", "apps/__init__.py"):
        (root / relative).write_text(code, encoding="utf-8")
    script = """
import importlib.abc
import runpy
import sys
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in ("galmuri.configuration.project", "galmuri.runtime"):
            raise AssertionError("generation imported " + fullname)
sys.meta_path.insert(0, RejectRuntime())
sys.argv = ["manage.py", "startapp", "sample", "--process"]
runpy.run_path("manage.py", run_name="__main__")
"""
    output = _run(root, "-c", script)
    assert 'APPS = ["apps.sample.app:sample"]' in output
    assert (root / "apps/sample/views/metadata.py").is_file()
    assert (root / "config/settings.py").read_text(encoding="utf-8") == code
    assert not (root / ".runtime").exists()


def test_two_apps_are_distinct_and_require_explicit_registration(tmp_path, capsys):
    root = start_project("example", tmp_path / "example")
    settings = root / "config/settings.py"
    original = settings.read_bytes()
    assert main(["startapp", "notes"], project_root=root) == 0
    assert main(["--project", str(root), "startapp", "catalog", "--process"]) == 0
    assert 'APPS = ["apps.notes.app:notes"]' in capsys.readouterr().out
    assert settings.read_bytes() == original
    assert load_project(root).apps == ()
    for name in ("notes", "catalog"):
        app_file = root / f"apps/{name}/app.py"
        code = app_file.read_text(encoding="utf-8")
        assert f'{name} = App(\n    name="{name}",' in code
        app_file.write_text(
            code.replace("    source=source,", "    source=source,\n    retrieval=None,"),
            encoding="utf-8",
        )
        assert (root / f"apps/{name}/source/local.py").is_file()
        assert (root / f"apps/{name}/skills/usage.md").is_file()
    assert '"pipeline": "catalog"' in (root / "apps/catalog/views/metadata.py").read_text(
        encoding="utf-8"
    )
    settings.write_text(
        original.decode().replace(
            "APPS = []", 'APPS = ["apps.notes.app:notes", "apps.catalog.app:catalog"]'
        ),
        encoding="utf-8",
    )
    synced = json.loads(_run(root, "manage.py", "sync"))
    assert synced["result"]["processed"] == 4
    for name in ("notes", "catalog"):
        output = _run(
            root,
            "manage.py",
            "call",
            "search",
            "--app",
            name,
            "--mode",
            "lexical",
            "--query",
            "welcome",
        )
        hits = json.loads(output)["result"]
        assert len(hits) == 1
        if name == "catalog":
            assert hits[0]["metadata"]["pipeline"] == "catalog"
    assert not (root / ".runtime/models").exists()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "_",
        "___",
        "../escape",
        "a/b",
        r"a\b",
        "with-dash",
        "a.b",
        "42app",
        "class",
        "apps",
        "config",
        "galmuri",
        "__init__",
        "__pycache__",
        "NUL",
        "COM1",
    ],
)
def test_invalid_names_fail_before_writing(tmp_path, name):
    root = start_project("example", tmp_path / "example")
    with pytest.raises(ValueError, match="Invalid name"):
        create_app(root, name)
    with pytest.raises(ValueError, match="Invalid name"):
        start_project(name, tmp_path / "not_created")
    assert [path.name for path in (root / "apps").iterdir()] == ["__init__.py"]
    assert not (tmp_path / "not_created").exists()


def test_existing_targets_preserve_user_files_and_settings(tmp_path):
    root = start_project("example", tmp_path / "example")
    app = create_app(root, "notes")
    user_file = app / "user.py"
    user_file.write_text("keep this", encoding="utf-8")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError):
        start_project("example", root)
    with pytest.raises(FileExistsError):
        create_project(root)
    with pytest.raises(FileExistsError):
        create_app(root, "notes", process=True)
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")


@pytest.mark.parametrize("dangling", [False, True])
def test_symbolic_link_targets_are_refused(tmp_path, dangling):
    root = start_project("example", tmp_path / "example")
    outside = tmp_path / "outside"
    if not dangling:
        outside.mkdir()
    _symlink(root / "apps/linked", outside)
    with pytest.raises(FileExistsError):
        create_app(root, "linked")
    _symlink(tmp_path / "linked_project", outside)
    with pytest.raises(FileExistsError):
        start_project("linked_project", tmp_path / "linked_project")
    with pytest.raises(FileExistsError):
        create_project(tmp_path / "linked_project")
    assert outside.exists() is not dangling
    if not dangling:
        assert not list(outside.iterdir())


def test_linked_apps_directory_is_refused(tmp_path):
    root = start_project("example", tmp_path / "example")
    (root / "apps/__init__.py").unlink()
    (root / "apps").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "__init__.py").write_text("", encoding="utf-8")
    _symlink(root / "apps", outside)
    with pytest.raises(FileExistsError):
        create_app(root, "notes")
    assert not (outside / "notes").exists()


def test_startapp_requires_project_structure_without_creating_it(tmp_path, capsys):
    assert main(["--project", str(tmp_path), "startapp", "notes"]) == 1
    assert "Expected a project" in capsys.readouterr().err
    assert not (tmp_path / "apps").exists()


@pytest.mark.parametrize("state", ["PREPARING", "COMPLETE"])
def test_state_write_failure_rolls_back_output_and_records_failed(tmp_path, monkeypatch, state):
    original = generation._state

    def fail(stream, value):
        if value == state:
            raise OSError("injected state failure")
        return original(stream, value)

    monkeypatch.setattr(generation, "_state", fail)
    target = tmp_path / "example"
    with pytest.raises(OSError, match="injected state failure"):
        start_project("example", target)
    assert json.loads((target / ".project.json").read_text())["state"] == "FAILED"
    assert [path.name for path in target.iterdir()] == [".project.json"]
    with pytest.raises(ValueError, match="Incomplete generation"):
        load_project(target)


def test_partial_app_write_preserves_concurrent_file_and_marks_failure(tmp_path, monkeypatch):
    root = start_project("example", tmp_path / "example")
    original = Path.open

    def conflicting_open(path, mode="r", *args, **kwargs):
        if mode == "x" and path == root / "apps/notes/source/local.py":
            with original(path, "w", encoding="utf-8") as stream:
                stream.write("# user file created concurrently\n")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", conflicting_open)
    with pytest.raises(FileExistsError):
        create_app(root, "notes")
    app = root / "apps/notes"
    assert json.loads((app / ".app.json").read_text())["state"] == "FAILED"
    assert not (app / "app.py").exists()
    assert (app / "source/local.py").read_text() == "# user file created concurrently\n"
    settings = root / "config/settings.py"
    settings.write_text(
        settings.read_text().replace("APPS = []", 'APPS = ["apps.notes.app:notes"]'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Incomplete generation"):
        load_project(root)


def test_preparing_project_is_rejected_before_importing_settings(tmp_path):
    root = start_project("example", tmp_path / "example")
    (root / ".project.json").write_text('{"schema": 1, "state": "PREPARING"}')
    (root / "config/settings.py").write_text("raise AssertionError('imported partial settings')")
    with pytest.raises(ValueError, match="Incomplete generation"):
        load_project(root)
    with pytest.raises(ValueError, match="Incomplete generation"):
        create_app(root, "notes")


def test_failure_preserves_user_replacement_of_generated_file(tmp_path, monkeypatch):
    root = start_project("example", tmp_path / "example")
    original = Path.open
    app = root / "apps/notes"

    def interrupted_open(path, mode="r", *args, **kwargs):
        if mode == "x" and path == app / "source/local.py":
            replacement = app / "user.tmp"
            replacement.write_text("# user replacement\n", encoding="utf-8")
            replacement.replace(app / "app.py")
            raise KeyboardInterrupt
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted_open)
    with pytest.raises(KeyboardInterrupt):
        create_app(root, "notes")
    assert (app / "app.py").read_text() == "# user replacement\n"
    assert json.loads((app / ".app.json").read_text())["state"] == "FAILED"
    assert not (app / "source").exists()


def test_incomplete_app_package_reference_is_checked_before_import(tmp_path):
    root = start_project("example", tmp_path / "example")
    app = create_app(root, "notes")
    (app / "__init__.py").write_text("raise AssertionError('imported partial app')")
    (app / ".app.json").write_text('{"schema": 1, "state": "PREPARING"}')
    settings = root / "config/settings.py"
    settings.write_text(
        settings.read_text().replace("APPS = []", 'APPS = ["apps.notes:notes"]'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Incomplete generation"):
        load_project(root)


def test_failure_preserves_user_edit_of_generated_file(tmp_path, monkeypatch):
    root = start_project("example", tmp_path / "example")
    original = Path.open
    app = root / "apps/notes"

    def interrupted_open(path, mode="r", *args, **kwargs):
        if mode == "x" and path == app / "source/local.py":
            (app / "app.py").write_text("# user edit in the same file\n", encoding="utf-8")
            raise OSError("generation interrupted")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted_open)
    with pytest.raises(OSError, match="generation interrupted"):
        create_app(root, "notes")
    assert (app / "app.py").read_text() == "# user edit in the same file\n"
    assert json.loads((app / ".app.json").read_text())["state"] == "FAILED"


def test_rollback_does_not_follow_replaced_parent_symlink(tmp_path, monkeypatch):
    root = start_project("example", tmp_path / "example")
    outside = tmp_path / "moved_source"
    # Verify the platform can create a link before beginning the interrupted generation.
    probe = tmp_path / "probe"
    _symlink(probe, outside)
    probe.unlink()
    original = Path.open
    app = root / "apps/notes"

    def interrupted_open(path, mode="r", *args, **kwargs):
        if mode == "x" and path == app / "skills/usage.md":
            (app / "source").rename(outside)
            (app / "source").symlink_to(outside, target_is_directory=True)
            raise OSError("generation directory replaced")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", interrupted_open)
    with pytest.raises(OSError, match="generation directory replaced"):
        create_app(root, "notes")
    assert (outside / "local.py").is_file()
    assert (outside / "__init__.py").is_file()
    assert (app / "source").is_symlink()
    assert json.loads((app / ".app.json").read_text())["state"] == "FAILED"
