"""Explicit opt-in: downloads real model weights and requires a real Qdrant server."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("FRAMEWORK_LIVE_QDRANT") != "1",
    reason="Set FRAMEWORK_LIVE_QDRANT=1 and QDRANT_URL for actual neural/Qdrant acceptance",
)
def test_generated_semantic_project_real_model_lifecycle(tmp_path):
    if importlib.util.find_spec("fastembed") is None:
        pytest.fail("Live acceptance requires framework-core[embeddings]")
    url = os.environ.get("QDRANT_URL")
    if not url:
        pytest.fail("Live acceptance requires QDRANT_URL")
    # Keep dynamically loaded generated app modules/model state outside the pytest process.
    project_root = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-m",
        "tools.retrieval_acceptance",
        "--project",
        str(tmp_path / "generated"),
        "--evidence",
        str(tmp_path / "evidence"),
        "--qdrant-url",
        url,
    ]
    result = subprocess.run(
        command, cwd=project_root, capture_output=True, text=True, timeout=600, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
