"""Run from project root: python -m tools.default_acceptance --help."""

import argparse
import json
from pathlib import Path

from .scenario import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="New nonexistent directory")
    parser.add_argument("--evidence", required=True, type=Path)
    options = parser.parse_args()
    report = run(options.project, options.evidence)
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
