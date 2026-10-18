import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from galmuri.contracts.files import FileRef, SourceConflict
from galmuri.sources.local import LocalFiles, ReadOnlyFiles


def test_changes_survive_connector_recreation_and_only_return_changed_files(tmp_path):
    (tmp_path / "old.md").write_text("old", encoding="utf-8")
    source = ReadOnlyFiles(tmp_path)
    first = source.changes(None)
    assert [(change.ref.key, change.deleted) for change in first.changes] == [("old.md", False)]
    assert json.loads(first.checkpoint)["format"] == 1
    assert source.changes(first.checkpoint).changes == ()

    (tmp_path / "old.md").write_text("updated", encoding="utf-8")
    (tmp_path / "new.md").write_text("added", encoding="utf-8")
    second = ReadOnlyFiles(tmp_path).changes(first.checkpoint)
    assert {change.ref.key for change in second.changes} == {"old.md", "new.md"}
    (tmp_path / "old.md").unlink()
    third = source.changes(second.checkpoint)
    assert len(third.changes) == 1
    assert third.changes[0].ref.key == "old.md"
    assert third.changes[0].deleted


def test_read_requires_discovered_version_and_returns_closed_bytes(tmp_path):
    path = tmp_path / "hello.txt"
    path.write_bytes(b"hello")
    source = ReadOnlyFiles(tmp_path)
    ref = source.scan()[0]
    file = source.read(ref)
    assert file.read() == b"hello"
    assert file.text == "hello"
    assert file.name == "hello.txt"
    path.write_bytes(b"other")
    with pytest.raises(SourceConflict):
        source.read(ref)
    assert source.current("hello.txt").version != ref.version


def test_write_is_conditional_and_discovered_without_internal_files(tmp_path):
    (tmp_path / "file.md").write_bytes(b"old")
    source = LocalFiles(tmp_path)
    ref = source.scan()[0]
    checkpoint = source.changes(None).checkpoint
    new_ref = source.write(ref.key, b"new", ref.version)
    assert new_ref.version != ref.version
    assert source.read(new_ref).content == b"new"
    assert [item.key for item in source.scan()] == ["file.md"]
    assert [change.ref for change in source.changes(checkpoint).changes] == [new_ref]
    with pytest.raises(SourceConflict):
        source.write(ref.key, b"stale", ref.version)
    assert source.read(new_ref).content == b"new"


def test_competing_writers_cannot_both_replace_same_expected_version(tmp_path):
    (tmp_path / "file.md").write_bytes(b"old")
    source = LocalFiles(tmp_path)
    ref = source.scan()[0]

    def replace(value):
        try:
            return LocalFiles(tmp_path).write(ref.key, value, ref.version)
        except SourceConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replace, [b"first", b"second"]))
    assert sum(result is not None for result in results) == 1


def test_read_only_source_has_no_write_capability(tmp_path):
    assert not callable(getattr(ReadOnlyFiles(tmp_path), "write", None))
    assert not callable(getattr(LocalFiles(tmp_path, writable=False), "write", None))
    assert callable(getattr(LocalFiles(tmp_path), "write", None))


@pytest.mark.parametrize(
    "key",
    [
        "../secret",
        "/secret",
        "folder/../../secret",
        "C:/secret",
        "a\\b",
        "x:y",
        "a//b",
        ".",
        ".framework-state/mutation.lock",
    ],
)
def test_read_and_write_reject_paths_outside_source_contract(tmp_path, key):
    source = LocalFiles(tmp_path)
    ref = FileRef(key, "old")
    with pytest.raises(ValueError):
        source.read(ref)
    with pytest.raises(ValueError):
        source.write(key, b"changed", "old")


def test_symlink_escape_is_never_read_or_written(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires a platform capability")
    source = LocalFiles(root)
    with pytest.raises(ValueError):
        source.current("link.txt")
    with pytest.raises(ValueError):
        source.write("link.txt", b"changed", "old")
    with pytest.raises(ValueError):
        source.scan()
    assert outside.read_bytes() == b"secret"


def test_missing_file_in_listing_is_rechecked_before_deletion(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_bytes(b"still here")
    source = ReadOnlyFiles(tmp_path)
    checkpoint = source.changes(None).checkpoint
    monkeypatch.setattr(source, "scan", lambda: ())
    result = source.changes(checkpoint)
    assert result.changes == ()
    assert "file.txt" in json.loads(result.checkpoint)["files"]


def test_checkpoint_is_scoped_to_source_and_invalid_checkpoint_fails(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    checkpoint = ReadOnlyFiles(first).changes(None).checkpoint
    with pytest.raises(ValueError):
        ReadOnlyFiles(second).changes(checkpoint)
    with pytest.raises(ValueError):
        ReadOnlyFiles(first).changes("not-json")


def test_nested_file_keys_are_portable(tmp_path):
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_bytes(b"nested")
    source = LocalFiles(tmp_path)
    ref = source.scan()[0]
    assert ref.key == "one/two/file.txt"
    updated = source.write(ref.key, b"updated", ref.version)
    assert source.read(updated).content == b"updated"


def test_failed_replacement_preserves_original_and_cleans_temporary_file(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_bytes(b"original")
    source = LocalFiles(tmp_path)
    ref = source.current("file.txt")

    def fail(*args, **kwargs):
        raise PermissionError("replacement denied")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        source.write(ref.key, b"new", ref.version)
    assert source.read(ref).content == b"original"
    assert list(tmp_path.glob(".framework-write-*")) == []


def test_discovery_failure_does_not_report_partial_success(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_bytes(b"original")
    source = ReadOnlyFiles(tmp_path)
    checkpoint = source.changes(None).checkpoint

    def denied(key):
        raise PermissionError("cannot read source")

    monkeypatch.setattr(source, "current", denied)
    with pytest.raises(PermissionError):
        source.changes(checkpoint)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Requires POSIX special files")
def test_nonregular_files_are_rejected_without_waiting_for_fifo_writer(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular files"):
        ReadOnlyFiles(tmp_path).current("pipe")
