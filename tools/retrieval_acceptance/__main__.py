"""Run from the project root: python -m tools.retrieval_acceptance --help."""

import argparse
import json
import os
from pathlib import Path

from .scenario import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path, help="New, nonexistent directory")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL"))
    parser.add_argument("--cache", default=os.environ.get("EMBEDDING_CACHE"))
    arguments = parser.parse_args()
    if not arguments.qdrant_url:
        parser.error("Provide --qdrant-url or QDRANT_URL")
    report = run(
        arguments.project,
        arguments.evidence,
        url=arguments.qdrant_url,
        cache=arguments.cache,
        api_key=os.environ.get("QDRANT_API_KEY"),
    )
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
