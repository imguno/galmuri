from pathlib import Path

import pytest

from galmuri.scaffolding.project import create_project


def test_scaffold_contains_runnable_sample_and_separate_responsibilities(tmp_path: Path):
    target = create_project(tmp_path / "example")
    expected = [
        "manage.py",
        "config/settings.py",
        "apps/sample/app.py",
        "apps/sample/source/local.py",
        "apps/sample/skills/usage.md",
        "apps/sample/fixtures/welcome.md",
        "apps/sample/fixtures/clinic.md",
    ]
    assert all((target / filename).is_file() for filename in expected)
    assert not list(target.rglob("*.exe"))
    assert "handler=" not in (target / "apps/sample/app.py").read_text()
    assert "ReadOnlyLocalProvider" in (target / "apps/sample/source/local.py").read_text()
    assert not (target / "apps/sample/ingestion").exists()


def test_scaffold_never_overwrites_existing_directory(tmp_path: Path):
    existing = tmp_path / "example"
    existing.mkdir()
    sentinel = existing / "mine.py"
    sentinel.write_text("my work", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_project(existing)
    assert sentinel.read_text(encoding="utf-8") == "my work"


def test_retrieval_preset_loads_without_connecting_or_downloading(tmp_path: Path):
    import subprocess
    import sys

    target = create_project(tmp_path / "semantic", retrieval=True)
    # Configuration imports are safe even without optional FastEmbed installed;
    # inference and remote connections happen only during operations.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from apps.sample.app import sample; "
            "assert sample.retrieval.mode == 'hybrid'; "
            "assert sample.retrieval.chunker.size == 600",
        ],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (target / "apps/sample/retrieval/configuration.py").is_file()
    assert (target / "apps/sample/fixtures/clinic.md").is_file()
    assert "qdrant/qdrant:v1.19.2@sha256:" in (target / "compose.yaml").read_text()
    assert not (create_project(tmp_path / "minimal") / "compose.yaml").exists()
