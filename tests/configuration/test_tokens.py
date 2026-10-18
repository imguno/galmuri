"""Credential publication must never expose an incomplete token to another host."""

import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from galmuri.configuration import tokens
from galmuri.configuration.project import Project
from galmuri.contracts.documents import Principal


def test_concurrent_first_project_tokens_publish_one_complete_private_value(tmp_path, monkeypatch):
    project = Project(tmp_path, (), tmp_path / "state", Principal(), {}, {})
    path = tmp_path / ".runtime" / "admin.token"
    contenders = 8
    ready = threading.Barrier(contenders)
    link = os.link

    def simultaneous_publish(candidate, destination):
        length = len(Path(candidate).read_text("utf-8"))
        assert length >= 40
        ready.wait(timeout=10)
        link(candidate, destination)

    monkeypatch.setattr(tokens.os, "link", simultaneous_publish)
    with ThreadPoolExecutor(max_workers=contenders) as pool:
        values = list(pool.map(lambda _: project.token(), range(contenders)))
    # Boolean checks avoid printing bearer credentials in a failed assertion.
    one_value = len(set(values)) == 1
    complete = all(len(value) >= 40 for value in values)
    published = path.read_text("utf-8") == values[0]
    assert one_value
    assert complete
    assert published
    assert list(path.parent.glob(".admin-token-*")) == []
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("existing", ["existing-host-credential", ""])
def test_existing_token_is_never_replaced(tmp_path, existing):
    path = tmp_path / "admin.token"
    path.write_text(existing, "utf-8")
    if existing:
        preserved = tokens.load_or_create_token(path) == existing
        assert preserved
    else:
        with pytest.raises(ValueError, match="must not be empty"):
            tokens.load_or_create_token(path)
    unchanged = path.read_text("utf-8") == existing
    assert unchanged
    assert list(tmp_path.glob(".admin-token-*")) == []


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_failed_prepublication_cleans_private_candidate(tmp_path, monkeypatch, operation):
    def fail(*args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(tokens.os, operation, fail)
    path = tmp_path / "admin.token"
    with pytest.raises(OSError, match="injected publication failure"):
        tokens.load_or_create_token(path)
    assert not path.exists()
    assert list(tmp_path.glob(".admin-token-*")) == []
