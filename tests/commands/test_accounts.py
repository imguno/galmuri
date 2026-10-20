"""Local bootstrap and credential publication own their failure/retry boundary."""

import io
import json
import os

import pytest

from galmuri.cli import main
from galmuri.commands.credential_files import publish
from galmuri.configuration import load_project
from galmuri.identity import AuthenticationError, IdentityStore
from galmuri.scaffolding.project import create_project

PASSWORD = "a synthetic strong password 123"


def test_generated_bootstrap_login_groups_and_scoped_mcp_token(tmp_path, monkeypatch, capsys):
    project = create_project(tmp_path / "generated")
    monkeypatch.delenv("FRAMEWORK_TOKEN", raising=False)
    monkeypatch.delenv("FRAMEWORK_TOKEN_FILE", raising=False)

    def run(*args, password=False):
        if password:
            monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
        assert main(list(args), project_root=project) == 0
        result = json.loads(capsys.readouterr().out)
        assert PASSWORD not in str(result)
        return result["result"]

    root = run("createsuperuser", "root", "--password-stdin", password=True)
    assert root["root"] and root["administrator"]
    user = run("createuser", "member", "--password-stdin", password=True)
    assert not user["root"]
    group = run("creategroup", "team")
    run("group-add", "team", "member")
    credential_file = project / ".runtime" / "member.token"
    result = run(
        "mcp-token",
        "member",
        "--scope",
        "read",
        "--app",
        "sample",
        "--token-file",
        str(credential_file),
    )
    assert "token" not in result
    directory = load_project(project).identity
    principal = directory.authenticate(credential_file.read_text().strip())
    assert principal.subject == user["id"] and group["id"] in principal.groups
    assert principal.authorize("read", "sample") and not principal.authorize("write", "sample")
    if os.name == "posix":
        assert credential_file.stat().st_mode & 0o777 == 0o600
    run("group-remove", "team", "member")
    assert not principal.groups
    session_file = project / ".runtime" / "session.token"
    run("login", "root", "--password-stdin", "--token-file", str(session_file), password=True)
    assert directory.authenticate(session_file.read_text().strip()).root
    run("logout", "--token-file", str(session_file))
    assert not session_file.exists()


@pytest.mark.parametrize("failure_at", [1, 2])
def test_failed_fsync_revokes_credential_cleans_only_owned_files_and_can_retry(
    tmp_path, monkeypatch, failure_at
):
    directory = IdentityStore(tmp_path / "accounts.db")
    user = directory.create_user("member", PASSWORD)
    credential = directory.issue_token(user["id"], "test")
    path = tmp_path / "token"
    real_fsync, attempts = os.fsync, []

    def fsync(descriptor):
        attempts.append(descriptor)
        if len(attempts) == failure_at:
            raise OSError("synthetic durability failure")
        return real_fsync(descriptor)

    if failure_at == 2 and os.name != "posix":
        pytest.skip("Directory fsync is a POSIX publication boundary")
    with monkeypatch.context() as fault:
        fault.setattr("galmuri.commands.credential_files.os.fsync", fsync)
        with pytest.raises(OSError, match="synthetic"):
            publish(directory, credential, path)
    assert not path.exists() and not list(tmp_path.glob(".credential-*"))
    with pytest.raises(AuthenticationError):
        directory.authenticate(credential["token"])
    replacement = directory.issue_token(user["id"], "retry")
    publish(directory, replacement, path)
    assert directory.authenticate(path.read_text().strip()).subject == user["id"]


def test_existing_credential_file_is_not_overwritten_and_new_token_is_revoked(tmp_path):
    directory = IdentityStore(tmp_path / "accounts.db")
    user = directory.create_user("member", PASSWORD)
    issued = directory.issue_token(user["id"], "test")
    target = tmp_path / "existing"
    target.write_text("operator file", encoding="utf-8")
    with pytest.raises(FileExistsError):
        publish(directory, issued, target)
    assert target.read_text() == "operator file"
    with pytest.raises(AuthenticationError):
        directory.authenticate(issued["token"])


@pytest.mark.skipif(os.name != "posix", reason="Directory fsync is a POSIX boundary")
def test_cleanup_failure_cannot_skip_revocation_or_mask_original_error(tmp_path, monkeypatch):
    from pathlib import Path

    directory = IdentityStore(tmp_path / "accounts.db")
    user = directory.create_user("member", PASSWORD)
    credential = directory.issue_token(user["id"], "test")
    real_fsync, calls = os.fsync, []

    def fsync(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:
            raise OSError("original durability failure")
        real_fsync(descriptor)

    def unlink(path, *args, **kwargs):
        raise OSError("synthetic cleanup failure")

    with monkeypatch.context() as fault:
        fault.setattr("galmuri.commands.credential_files.os.fsync", fsync)
        fault.setattr(Path, "unlink", unlink)
        with pytest.raises(OSError, match="original durability failure"):
            publish(directory, credential, tmp_path / "token")
    with pytest.raises(AuthenticationError):
        directory.authenticate(credential["token"])


def test_explicit_empty_or_revoked_credentials_never_fall_back_to_anonymous(tmp_path, monkeypatch):
    project = create_project(tmp_path / "generated")
    loaded = load_project(project)
    monkeypatch.delenv("FRAMEWORK_TOKEN", raising=False)
    monkeypatch.delenv("FRAMEWORK_TOKEN_FILE", raising=False)
    assert loaded.caller().subject == "anonymous"
    monkeypatch.setenv("FRAMEWORK_TOKEN", "")
    with pytest.raises(AuthenticationError):
        loaded.caller()
    monkeypatch.delenv("FRAMEWORK_TOKEN")
    token_file = project / "empty.token"
    token_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("FRAMEWORK_TOKEN_FILE", str(token_file))
    with pytest.raises(AuthenticationError):
        loaded.caller()
