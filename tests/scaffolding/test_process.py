"""The optional pipeline scaffold is runnable, small and uses actual function refs."""

from dataclasses import replace

import pytest

from galmuri import Pipeline, Principal
from galmuri.cli import main
from galmuri.configuration import load_project
from galmuri.runtime import Runtime
from galmuri.scaffolding.project import create_project


def test_custom_process_scaffold_executes_named_stages_and_publishes_metadata(tmp_path):
    target = create_project(tmp_path / "pipeline", process=True)
    project = load_project(target)
    assert isinstance(project.apps[0].process, Pipeline)
    assert [step.name for step in project.apps[0].process.steps] == [
        "parse",
        "normalize",
        "label",
        "prepare",
    ]
    # Model quality is verified separately; here the generated stage code is executed.
    runtime = Runtime(project.database, [replace(project.apps[0], retrieval=None)])
    assert runtime.sync()["processed"] == 2
    found = runtime.search("sample", "CLINIC-42", Principal())
    assert len(found) == 1
    assert found[0]["metadata"]["pipeline"] == "sample"
    assert found[0]["text"].endswith("\n")
    assert (target / "apps/sample/views/normalization.py").is_file()
    assert (target / "apps/sample/views/metadata.py").is_file()
    assert "process=process" in (target / "apps/sample/app.py").read_text()
    assert "NotImplementedError" not in (target / "apps/sample/views/normalization.py").read_text()


def test_cli_process_preset_creates_without_source_read_or_model_inference(tmp_path, capsys):
    target = tmp_path / "pipeline"
    assert main(["new", str(target), "--process"]) == 0
    assert str(target) in capsys.readouterr().out
    assert not (target / ".runtime").exists()


def test_preset_conflicts_fail_before_creating_any_project_files(tmp_path):
    target = tmp_path / "invalid"
    with pytest.raises(ValueError, match="preset"):
        create_project(target, process=True, retrieval=False)
    assert not target.exists()
