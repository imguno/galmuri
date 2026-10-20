"""A readiness barrier waits for readable output and still has a bounded failure."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from .conftest import Process


def waiting_process(directory):
    worker = object.__new__(Process)
    worker.directory = directory
    worker.process = SimpleNamespace(poll=lambda: None)
    return worker


def test_readiness_waits_through_transient_sharing_lock(tmp_path, monkeypatch):
    path = tmp_path / "ready.json"
    path.write_text('{"ready": true}', encoding="utf-8")
    original = Path.read_text
    attempts = []

    def temporarily_locked(candidate, *args, **kwargs):
        if candidate == path:
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError("publication is temporarily locked")
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", temporarily_locked)
    assert waiting_process(tmp_path).wait_file("ready.json") == {"ready": True}
    assert len(attempts) == 2


def test_readiness_does_not_hide_permanent_read_failure(tmp_path, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError("still locked")

    ticks = iter((0, 31))
    monkeypatch.setattr(Path, "read_text", locked)
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    with pytest.raises(AssertionError, match="Worker did not reach ready.json") as failure:
        waiting_process(tmp_path).wait_file("ready.json")
    assert isinstance(failure.value.__cause__, PermissionError)
