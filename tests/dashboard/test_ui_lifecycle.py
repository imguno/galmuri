"""The actual UI must fence a private response arriving after account logout."""

import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import pytest


def test_logout_discards_in_flight_private_response():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional Node runtime is required for the UI lifecycle harness")
    script = Path(__file__).with_name("ui_lifecycle.cjs")
    ui = files("galmuri.exposure.dashboard.assets").joinpath("app.js")
    result = subprocess.run(
        [node, str(script), str(ui)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert "fences late document responses" in result.stdout
