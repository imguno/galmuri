"""Publication scanner reports locations, never matching values or snippets."""

import argparse
import json
from pathlib import Path

from tools.publication.scan import inventory_workspace, scan_staged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    try:
        report = scan_staged(args.repository)
        report["schema"] = 1
        if args.workspace is not None:
            report["workspace_inventory"] = inventory_workspace(args.workspace)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError):
        print("Publication scan failed; no source contents were logged")
        return 2
    print(
        json.dumps(
            {
                "scope": report["scope"],
                "checked_files": report["checked_files"],
                "findings": len(report["findings"]),
                "workspace_paths": len(report.get("workspace_inventory", ())),
            }
        )
    )
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
