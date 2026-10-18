"""Exercise installed CLI, scaffold, pipeline, lexical search, accounts and assets."""

import json
import os
import secrets
import subprocess
import sys
from importlib import metadata, util
from pathlib import Path

import duru

import galmuri

ENVIRONMENT = {
    name: value
    for name, value in os.environ.items()
    if name not in {"PYTHONPATH", "PYTHONHOME", "FRAMEWORK_TOKEN_FILE", "FRAMEWORK_TOKEN"}
}


def command(*arguments, input=None, env=None):
    completed = subprocess.run(
        [str(value) for value in arguments],
        input=input,
        env=ENVIRONMENT if env is None else env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return completed.stdout


def manage(project, *arguments, **options):
    return json.loads(command(sys.executable, project / "manage.py", *arguments, **options))


for module in (galmuri, duru):
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
for name in ("framework", "resource_access"):
    assert util.find_spec(name) is None, "An old import namespace leaked into the installation"
for name in ("galmuri", "duru"):
    assert metadata.metadata(name)["License-Expression"] == "BSD-3-Clause"
package = Path(galmuri.__file__).parent
assert (package / "exposure/grpc/exposure.proto").read_bytes()
for name in ("index.html", "app.js", "style.css"):
    assert (package / "exposure/dashboard/assets" / name).read_bytes()
skill = Path(sys.prefix) / "share/galmuri/skills/using-galmuri/SKILL.md"
assert skill.read_text(encoding="utf-8").startswith("---"), "Installed agent skill is missing"
cli = Path(sys.executable).parent / ("galmuri.exe" if sys.platform == "win32" else "galmuri")
assert "--help" in command(cli, "--help")
project = Path.cwd() / "sample"
command(cli, "new", project, "--process")
app = project / "apps/sample/app.py"
original = app.read_text(encoding="utf-8")
assert 'name="sample",' in original
app.write_text(
    original.replace('name="sample",', 'name="sample",\n    retrieval=None,'), encoding="utf-8"
)
manage(project, "sync")
described = manage(project, "call", "describe", "--app", "sample")
assert (
    described["ok"]
    and described["result"]["configuration"]["ingestion"]["implementation"] == "pipeline"
)
assert described["result"]["configuration"]["retrieval"] == {"mode": "lexical"}
found = manage(project, "call", "search", "--app", "sample", "--query", "welcome")
assert found["ok"] and found["result"]
assert found["result"][0]["metadata"]["pipeline"] == "sample"
password = secrets.token_urlsafe(32) + "\n"
created = manage(project, "createsuperuser", "release-check", "--password-stdin", input=password)
assert created["ok"] and created["result"]["root"]
token = project / ".runtime/release.token"
logged_in = manage(
    project, "login", "release-check", "--password-stdin", "--token-file", token, input=password
)
assert logged_in["ok"] and token.is_file()
environment = dict(ENVIRONMENT, FRAMEWORK_TOKEN_FILE=str(token))
assert manage(project, "call", "index_status", "--app", "sample", env=environment)["ok"]
print("Installed Galmuri: CLI, custom pipeline, lexical search, accounts, assets and skill passed")
