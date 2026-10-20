"""Execute the documented user-owned parser/exporter without model or framework edits."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


def blocks(text, language):
    return re.findall(rf"```{language}\n(.*?)\n```", text, re.DOTALL)


def section_code(text, heading):
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    return blocks(section, "python")


def test_bilingual_connector_and_exporter_tutorial_runs_as_written(tmp_path):
    pytest.importorskip("mcp")
    root = Path(__file__).resolve().parents[2]
    english = (root / "guides/build-an-integration.md").read_text(encoding="utf-8")
    korean = (root / "guides/build-an-integration.ko.md").read_text(encoding="utf-8")
    snippets = blocks(english, "python")
    assert snippets == blocks(korean, "python"), "The two guides must run the same examples"
    assert len(snippets) == 12
    registration = snippets[0]
    parser_code = section_code(english, "## 2.")[0]
    app_code = section_code(english, "## 3.")[0]
    exporter_code, exporter_settings = section_code(english, "## 6.")
    client_code = section_code(english, "## Connect your RAG client")[0]
    provider_code, provider_app, provider_registration = section_code(english, "## 7.")
    created = subprocess.run(
        [sys.executable, "-m", "galmuri", "startproject", "catalog"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    project = tmp_path / "catalog"

    def run(*arguments):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run("manage.py", "startapp", "sample")
    assert not (project / ".runtime").exists()
    settings = project / "config/settings.py"
    settings.write_text(
        settings.read_text(encoding="utf-8") + "\n" + registration, encoding="utf-8"
    )
    views = project / "apps/sample/views"
    views.mkdir()
    (views / "__init__.py").write_text("", encoding="utf-8")
    (views / "articles.py").write_text(parser_code, encoding="utf-8")
    (project / "apps/sample/app.py").write_text(app_code, encoding="utf-8")
    (project / "apps/sample/fixtures/article.json").write_text(
        blocks(english, "json")[0], encoding="utf-8"
    )

    run("manage.py", "sync")
    response = json.loads(
        run(
            "manage.py",
            "call",
            "search",
            "--app",
            "sample",
            "--mode",
            "lexical",
            "--query",
            "quasar",
        )
    )
    assert response["ok"]
    article = response["result"][0]
    assert article["text"].startswith("Observatory handbook")
    assert article["metadata"]["format"] == "article"
    read = json.loads(
        run(
            "manage.py",
            "call",
            "read",
            "--app",
            "sample",
            "--params",
            json.dumps({"document_key": article["key"]}),
        )
    )
    assert read["result"]["text"] == article["text"]
    (project / "mcp_client.py").write_text(client_code, encoding="utf-8")
    assert "Observatory handbook" in run("mcp_client.py")
    exporters = project / "exporters"
    exporters.mkdir()
    (exporters / "__init__.py").write_text("", encoding="utf-8")
    (exporters / "articles.py").write_text(exporter_code, encoding="utf-8")
    settings.write_text(
        settings.read_text(encoding="utf-8") + "\n" + exporter_settings, encoding="utf-8"
    )
    exported = run("manage.py", "serve", "articles", "--workers", "0")
    assert [json.loads(line) for line in exported.splitlines()] == response["result"]
    run("manage.py", "startapp", "manuals")
    manuals = project / "apps/manuals"
    (manuals / "source/manual.py").write_text(provider_code, encoding="utf-8")
    (manuals / "app.py").write_text(provider_app, encoding="utf-8")
    settings.write_text(
        settings.read_text(encoding="utf-8") + "\n" + provider_registration, encoding="utf-8"
    )
    run("manage.py", "sync")
    second = json.loads(run("manage.py", "call", "search", "--app", "manuals", "--query", "quasar"))
    assert second["result"][0]["key"] == "guide://manual"
    assert "custom connector" in second["result"][0]["text"]
    assert "Observatory handbook" in run(
        "manage.py", "call", "search", "--app", "sample", "--query", "quasar"
    )
