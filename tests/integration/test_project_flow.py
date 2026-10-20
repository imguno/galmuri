import json
import os
import subprocess
import sys
from pathlib import Path

from galmuri.configuration import load_project
from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.http import HttpAdapter
from galmuri.exposure.service import Service
from galmuri.scaffolding import create_project
from galmuri.workers.remote import HttpWorker


def test_generated_project_sync_permissions_updates_and_deletion(tmp_path: Path):
    root = create_project(tmp_path / "sample_project", retrieval=False)
    project = load_project(root)
    runtime = project.runtime()
    runtime.sync()
    anonymous = Principal()
    developer = project.principal
    assert runtime.search("sample", "welcome", anonymous)
    assert not runtime.search("sample", "deployment", anonymous)
    restricted = runtime.search("sample", "deployment", developer)
    assert restricted
    welcome = runtime.search("sample", "welcome", developer)[0]
    runtime.write(
        "sample",
        welcome["key"],
        "# Updated\n\nNew onboarding instructions.",
        developer,
        welcome["version"],
    )
    runtime.drain()
    assert runtime.search("sample", "onboarding", anonymous)
    path = root / "apps/sample/fixtures/development.dev.md"
    path.unlink()
    runtime.sync()
    assert not runtime.search("sample", "deployment", developer)


def test_remote_worker_uses_http_contract_and_does_not_require_database_sharing(tmp_path: Path):
    root = create_project(tmp_path / "remote_project", retrieval=False)
    project = load_project(root)
    coordinator = project.runtime()
    coordinator.collect("sample", force=True)
    assert not coordinator.search("sample", "welcome", project.principal)
    adapter = HttpAdapter(
        Service(coordinator),
        port=0,
        authenticator=TokenAuthenticator(
            {
                "worker-token": project.principal,
            }
        ),
    )
    with adapter.server() as server:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        worker = HttpWorker(
            endpoint, "worker-token", {app.name: app for app in project.apps}, "remote"
        )
        while worker.run_once():
            pass
    assert coordinator.search("sample", "welcome", project.principal)
    assert {row["worker"] for row in coordinator.status()["attempts"]} == {"remote"}


def test_module_cli_and_generated_entrypoint_work_without_executable_binaries(tmp_path: Path):
    root = create_project(tmp_path / "cli_project", retrieval=False)
    completed = subprocess.run(
        [sys.executable, str(root / "manage.py"), "sync"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["result"]["processed"] == 2
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "manage.py"),
            "call",
            "search",
            "--app",
            "sample",
            "--query",
            "welcome",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["result"]
