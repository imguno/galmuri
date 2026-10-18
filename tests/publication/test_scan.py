"""Only staged bytes are public inputs; reports never reproduce matching values."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.publication import inventory_workspace, scan_staged
from tools.publication.patterns import content_findings


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


def stage(repository, name):
    subprocess.run(["git", "-C", str(repository), "add", name], check=True, capture_output=True)


def test_index_includes_staged_secret_even_when_worktree_is_clean(repository):
    path = repository / "example.py"
    token = "ghp_" + "A" * 36
    path.write_text("token = " + token, encoding="utf-8")
    stage(repository, path.name)
    path.write_text("value = 1", encoding="utf-8")
    report = scan_staged(repository)
    assert report["findings"] == [{"kind": "github_token", "path": path.name, "line": 1}]
    assert token not in json.dumps(report)
    stage(repository, path.name)
    assert scan_staged(repository)["findings"] == []
    path.write_text("token = " + token, encoding="utf-8")
    assert scan_staged(repository)["findings"] == []


@pytest.mark.parametrize(
    "name", [".env", "client.pem", ".runtime/accounts.sqlite", "docs/decisions/note.md"]
)
def test_private_index_paths_are_rejected(repository, name):
    path = repository / name
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text("synthetic", encoding="utf-8")
    stage(repository, name)
    assert scan_staged(repository)["findings"][0]["path"] == name


def test_cli_exit_status_and_serialized_report_are_redacted(repository):
    token = "xoxb-" + "1234567890-" * 4
    (repository / "example.py").write_text("token = " + token, encoding="utf-8")
    stage(repository, "example.py")
    output = repository / "report.json"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.publication",
            "--repository",
            str(repository),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert run.returncode == 1
    assert token not in run.stdout + run.stderr + output.read_text(encoding="utf-8")
    assert json.loads(output.read_text())["findings"][0]["kind"] == "slack_token"


def test_disposable_dsn_exception_does_not_allow_other_test_credentials():
    safe = b"postgresql://galmuri:galmuri-test-only@127.0.0.1:55437/galmuri"
    assert list(content_findings("tests/example.py", safe)) == []
    altered = safe.replace(b"galmuri-test-only", b"another-password")
    findings = list(content_findings("tests/example.py", altered))
    assert findings == [{"kind": "credential_dsn", "path": "tests/example.py", "line": 1}]
    assert "another-password" not in str(findings)


@pytest.mark.parametrize(
    "kind, candidate",
    [
        ("github_token", "github_pat_" + "A" * 48),
        ("openai_token", "sk-proj-" + "A" * 48),
        ("stripe_token", "sk_live_" + "A" * 24),
        ("aws_access_key", "AKIA" + "A" * 16),
        ("private_key", "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ],
)
def test_structural_credentials_report_only_locations(kind, candidate):
    findings = list(content_findings("source.py", candidate.encode()))
    assert findings == [{"kind": kind, "path": "source.py", "line": 1}]
    assert candidate not in json.dumps(findings)


def test_workspace_inventory_does_not_read_credentials_or_descend_into_private_roots(
    tmp_path, monkeypatch
):
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/private.token").write_text("not opened", encoding="utf-8")
    (tmp_path / ".env").write_text("not opened", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/hidden.token").write_text("not inventoried", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("Workspace inventory must not read private file contents")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    paths = {item["path"] for item in inventory_workspace(tmp_path)}
    assert paths == {".runtime/", ".env"}
