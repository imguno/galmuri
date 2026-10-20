"""Opt-in real weights, unchanged source-only scaffold and verified account/group ACLs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("FRAMEWORK_LIVE_DEFAULTS") != "1",
    reason="Set FRAMEWORK_LIVE_DEFAULTS=1 for actual default multilingual-model acceptance",
)
def test_source_only_scaffold_real_local_model(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.default_acceptance",
            "--project",
            str(tmp_path / "generated"),
            "--evidence",
            str(tmp_path / "evidence"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "evidence" / "summary.json").read_text(encoding="utf-8"))
    checks = {item["name"] for item in report["checks"]}
    assert {
        "source_only_default_public_read_without_fabricated_owner",
        "verified_administrator_has_no_document_acl_bypass",
        "verified_root_acl_bypass_with_scope_app_and_mid_io_revocation_limits",
        "dynamic_group_membership_without_embedding_rebuild",
        "expired_and_revoked_credentials_do_not_fall_back_to_public_access",
    } <= checks
