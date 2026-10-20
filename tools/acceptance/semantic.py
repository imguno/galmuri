"""Opt-in live LLM acceptance against a generated neural/Qdrant project.

The supplied disposable container must have the framework, FastEmbed and MCP
installed, and reach Qdrant. Authentication belongs to the host's Codex CLI.
"""

import argparse
import json
import uuid
from pathlib import Path

from .client import query
from .docker_host import DockerProject
from .evidence import _envelope, check


class SemanticHost(DockerProject):
    def __init__(self, container, qdrant_url, cache):
        super().__init__(
            container,
            [
                "--env",
                "QDRANT_URL=" + qdrant_url,
                "--env",
                "EMBEDDING_CACHE=" + cache,
            ],
            prefix="semantic-llm",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--cache", default="/tmp/embedding-cache")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    host = SemanticHost(args.container, args.qdrant_url, args.cache)
    host.execute("python", "-m", "galmuri", "new", host.project, "--retrieval")
    code = "CARE-" + uuid.uuid4().hex[:12].upper()
    settings = (
        '\nimport os\nLOCAL_PRINCIPAL = Principal("public-reader") '
        'if os.environ.get("ACCEPTANCE_ROLE") == "public" else LOCAL_PRINCIPAL\n'
    )
    host.execute(
        "python",
        "-c",
        "from pathlib import Path; p=Path(" + repr(host.project) + "); "
        "s=p/'config/settings.py'; s.write_text(s.read_text()+" + repr(settings) + "); "
        "(p/'apps/sample/fixtures/clinic.md').write_text("
        + repr(
            "# 진료 안내\n\n아픈 사람은 병원의 의사에게 진료를 받습니다.\n"
            "예약 확인 번호는 " + code + "입니다.\n"
        )
        + ",encoding='utf-8')",
    )
    sync = host.command("sync")
    if not sync["ok"]:
        raise AssertionError(sync)
    question = "몸이 좋지 않을 때 누구를 찾아가야 하나요? 예약 확인 번호도 알려주세요."
    paraphrase = "몸이 좋지 않을 때 누구를 찾아가야 하나요?"
    lexical = host.command(
        "call", "search", "--app", "sample", "--mode", "lexical", "--query", paraphrase
    )
    vector = host.command(
        "call", "search", "--app", "sample", "--mode", "vector", "--query", paraphrase
    )
    if lexical != {"ok": True, "result": []}:
        raise AssertionError("Paraphrase unexpectedly matched the lexical baseline")
    if not vector["ok"] or vector["result"][0]["key"] != "clinic.md":
        raise AssertionError("Real neural retrieval did not rank the relevant document first")
    answer = query(host, "public", question, args.output / "reader")
    result = check(
        args.output / "reader",
        answer,
        expected_key="clinic.md",
        required=(code,),
        forbidden=("DEPLOY-",),
    )
    events = [
        json.loads(line)
        for line in (args.output / "reader/events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    searches = [
        e["item"]
        for e in events
        if e.get("type") == "item.completed" and e["item"].get("tool") == "sample_search"
    ]
    if not any(
        any(
            doc.get("search_mode") in {"vector", "hybrid"}
            for doc in _envelope(call.get("result") or {}).get("result", [])
        )
        for call in searches
    ):
        raise AssertionError("LLM did not use semantic search")
    embedding = vector["result"][0]["embedding"]
    summary = {
        "passed": True,
        "project": host.project,
        "model": embedding["model"],
        "dimensions": embedding["dimensions"],
        "lexical": lexical,
        "vector": vector,
        "sync": sync,
        "llm": result,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"passed": True, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
