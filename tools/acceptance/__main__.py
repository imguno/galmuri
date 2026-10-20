"""Generate, run and query a project with a real external LLM client."""

import argparse
import json
import secrets
from pathlib import Path

from tools.acceptance.client import query
from tools.acceptance.container import Host
from tools.acceptance.evidence import check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="framework-access:acceptance")
    parser.add_argument("--output", type=Path, required=True, help="New directory for evidence")
    parser.add_argument("--timeout", type=int, default=180)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    suffix = secrets.token_hex(4)
    public_key, private_key = f"parcel-{suffix}.md", f"maintenance-{suffix}.dev.md"
    before = "SKY-" + secrets.token_hex(4).upper()
    after = "SKY-" + secrets.token_hex(4).upper()
    private = "DEV-" + secrets.token_hex(4).upper()
    locker = "Locker-" + secrets.token_hex(2).upper()
    public_question = "observatory parcel 안내에 적힌 수령 장소와 현재 수령 코드를 알려줘."
    private_question = "maintenance cabinet 안내의 접근 코드를 알려줘."

    def document(code):
        return f"# Observatory parcel\n\nCollection location: {locker}.\nCollection code: {code}.\n"

    expectations = {
        "public_key": public_key,
        "private_key": private_key,
        "before": before,
        "after": after,
        "private": private,
        "locker": locker,
    }
    (output / "ground-truth.json").write_text(json.dumps(expectations), encoding="utf-8")
    results = {}
    (output / "summary.json").write_text('{"state":"RUNNING"}', encoding="utf-8")
    try:
        with Host(arguments.image, output / "workspace") as host:
            host.configure(
                {
                    public_key: document(before),
                    private_key: f"# Maintenance cabinet\n\nAccess code: {private}.\n",
                }
            )
            sync = host.sync()
            if not sync["ok"] or sync["result"]["processed"] != 4:
                raise AssertionError("Generated project failed initial sample ingestion")

            def scenario(name, role, question, **expected):
                print(f"Running live LLM scenario: {name}", flush=True)
                answer = query(host, role, question, output / name, timeout=arguments.timeout)
                results[name] = check(output / name, answer, **expected)
                print(f"Passed: {name}", flush=True)

            scenario(
                "public",
                "public",
                public_question,
                expected_key=public_key,
                required=(locker, before),
                forbidden=(private, after),
            )
            scenario(
                "denied",
                "public",
                private_question,
                forbidden=(private,),
                search_terms=("maintenance", "cabinet"),
            )
            scenario(
                "developer", "dev", private_question, expected_key=private_key, required=(private,)
            )
            host.replace(public_key, document(after))
            if not host.sync()["ok"]:
                raise AssertionError("Updated document failed ingestion")
            scenario(
                "updated",
                "public",
                public_question,
                expected_key=public_key,
                required=(locker, after),
                forbidden=(before, private),
            )
            host.replace(public_key, None)
            if not host.sync()["ok"]:
                raise AssertionError("Deleted document failed collection")
            scenario(
                "deleted",
                "public",
                public_question,
                forbidden=(before, after, private),
                search_terms=("observatory", "parcel"),
            )
    except BaseException as error:
        (output / "summary.json").write_text(
            json.dumps(
                {"state": "FAILED", "error_type": type(error).__name__, "scenarios": results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise
    (output / "summary.json").write_text(
        json.dumps({"state": "PASSED", "scenarios": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output / "summary.json")


if __name__ == "__main__":
    main()
