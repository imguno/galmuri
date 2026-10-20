"""Run with python -m tools.search_quality --output .verification/search-quality.json."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from tools.search_quality.fixtures import FIXTURE_REVISION
from tools.search_quality.runner import environment, evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--documents",
        nargs="+",
        type=int,
        default=[100, 1000],
        help="Distractor counts; the fixed relevance corpus is added to each (default: 100 1000).",
    )
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if any(count < 0 for count in args.documents) or args.repeats < 1:
        parser.error("Document counts must be nonnegative and repeats must be positive")
    report = {
        "fixture": FIXTURE_REVISION,
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "repeats": args.repeats,
        "limit": 3,
        "scope": (
            "Small hand-authored synthetic fixture; not a general benchmark. "
            "Both engines query the same normally published SQLite documents. "
            "The indexed policy is recorded in each run's search metadata; the former baseline "
            "requires all whitespace-separated substrings. Timings include each engine's "
            "database/ACL path and use warmed, alternating runs. No external embeddings or LLM."
        ),
        "runs": [],
    }
    for count in args.documents:
        result = evaluate(count, args.repeats)
        report["runs"].append(result)
        print(
            json.dumps(
                {"documents": result["documents"], "summary": result["summary"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Report: {args.output}", flush=True)


if __name__ == "__main__":
    main()
