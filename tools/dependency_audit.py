"""Audit the installed dependency set without suppressing vulnerability advisories."""

import argparse
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

LOCAL = {"galmuri", "duru"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory, editable = [], []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        local = bool(direct.get("dir_info", {}).get("editable"))
        if local:
            editable.append(name)
            if name.lower().replace("_", "-") not in LOCAL:
                raise ValueError("Unexpected editable dependency; audit it explicitly first")
        inventory.append({"name": name, "version": distribution.version, "editable": local})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_name("dependency-inventory.json").write_text(
        json.dumps(sorted(inventory, key=lambda row: row["name"].lower()), indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"editable_projects_not_in_registry_audit": sorted(editable)}))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--local",
            "--skip-editable",
            "--format",
            "json",
            "--output",
            str(args.output),
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
