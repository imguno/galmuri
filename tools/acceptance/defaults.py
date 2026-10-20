"""Actual neural-model account-token LLM/MCP acceptance for a source-only App."""

import argparse
import json
import secrets
import uuid
from pathlib import Path

from .client import query
from .docker_host import DockerProject
from .evidence import check


class AccountProject(DockerProject):
    """Roles select private credential files; they never assert an account identity."""

    def token_file(self, role):
        return self.project + "/.runtime/acceptance-" + role + ".token"

    def mcp_arguments(self, role):
        return [
            "exec",
            "-i",
            *self.environment,
            "--env",
            "FRAMEWORK_TOKEN_FILE=" + self.token_file(role),
            self.container,
            "python",
            self.project + "/manage.py",
            "serve",
            "mcp",
            "--workers",
            "0",
        ]

    def password_command(self, password, *arguments):
        raw = self.execute(
            "python",
            self.project + "/manage.py",
            *arguments,
            "--password-stdin",
            input=password + "\n",
        )
        return json.loads(raw.strip().splitlines()[-1])

    def authenticated_command(self, role, *arguments):
        raw = self.execute(
            "env",
            "FRAMEWORK_TOKEN_FILE=" + self.token_file(role),
            "python",
            self.project + "/manage.py",
            *arguments,
        )
        return json.loads(raw.strip().splitlines()[-1])


def provision(host, documents):
    """Passwords use stdin; token secrets stay in private container files."""
    passwords = {name: secrets.token_urlsafe(32) for name in ("root", "administrator", "member")}
    root = host.password_command(passwords["root"], "createsuperuser", "root")
    admin = host.password_command(
        passwords["administrator"], "createuser", "administrator", "--administrator"
    )
    member = host.password_command(passwords["member"], "createuser", "member")
    assert root["result"]["root"] and not admin["result"]["root"]
    assert admin["result"]["administrator"]
    group = host.command("creategroup", "team")
    host.command("group-add", "team", "member")
    host.password_command(
        passwords["root"], "login", "root", "--token-file", host.token_file("operator")
    )
    tokens = {}
    for role in ("root", "administrator", "member"):
        tokens[role] = host.command(
            "mcp-token",
            role,
            "--scope",
            "read",
            "--app",
            "sample",
            "--token-file",
            host.token_file(role),
        )["result"]
    inventory = host.authenticated_command(
        "operator", "call", "permission_inventory", "--app", "sample"
    )
    assert inventory["ok"] and inventory["result"]["total"] == len(documents)
    permissions = []
    for document in inventory["result"]["items"]:
        params = {
            "document_key": document["key"],
            "readers": ["group:" + group["result"]["id"]],
            "writers": [],
            "expected_revision": document["permissions_revision"],
        }
        updated = host.authenticated_command(
            "operator",
            "call",
            "document_permissions",
            "--app",
            "sample",
            "--params",
            json.dumps(params),
        )
        assert updated["ok"]
        permissions.append(updated["result"])
    modes = json.loads(
        host.execute(
            "python",
            "-c",
            "from pathlib import Path; import json; "
            "p=Path(" + repr(host.project) + ")/'.runtime'; "
            "print(json.dumps({f.name:oct(f.stat().st_mode & 0o777) "
            "for f in p.glob('acceptance-*.token')}))",
        )
    )
    assert len(modes) == 4 and set(modes.values()) == {"0o600"}
    return {
        "root": root["result"],
        "administrator": admin["result"],
        "member": member["result"],
        "group": group["result"],
        "credentials": tokens,
        "token_file_modes": modes,
        "permissions": permissions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--cache", default="/models")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--process", action="store_true", help="Exercise the custom pipeline preset"
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Use FRAMEWORK_POSTGRES_DSN from the Docker container and an isolated schema",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    host = AccountProject(
        args.container,
        ["--env", "EMBEDDING_CACHE=" + args.cache],
        prefix="postgres-llm" if args.postgres else "identity-llm",
    )
    preset = ["--process"] if args.process else []
    host.execute("python", "-m", "galmuri", "new", host.project, *preset)
    namespace = None
    if args.postgres:
        # Keep the DSN in the container environment: no credentials in generated
        # project files, command arguments or acceptance evidence.
        host.execute(
            "python",
            "-c",
            "import os; assert os.environ.get('FRAMEWORK_POSTGRES_DSN'), "
            "'Configure FRAMEWORK_POSTGRES_DSN in the acceptance container'",
        )
        namespace = "acceptance_llm_" + uuid.uuid4().hex
        settings = (
            "\nimport os\n"
            "DATABASES = {'default': {'ENGINE': 'postgresql', "
            "'DSN': os.environ['FRAMEWORK_POSTGRES_DSN'], "
            f"'SCHEMA': {namespace!r}}}}}\n"
            "IDENTITY_DATABASE = 'default'\n"
        )
        host.execute(
            "python",
            "-c",
            "from pathlib import Path; "
            f"p=Path({host.project!r})/'config/settings.py'; "
            f"p.write_text(p.read_text(encoding='utf-8')+{settings!r},encoding='utf-8')",
        )
    code = "CARE-" + uuid.uuid4().hex[:12].upper()
    text = (
        "# 진료 안내\n\n아픈 사람은 병원의 의사에게 진료를 받습니다.\n예약 확인 번호는 "
        + code
        + "입니다.\n"
    )
    host.execute(
        "python",
        "-c",
        "from pathlib import Path; p=Path(" + repr(host.project) + "); "
        "(p/'apps/sample/fixtures/clinic.md').write_text(" + repr(text) + ",encoding='utf-8')",
    )
    sync = host.command("sync")
    describe = host.command("call", "describe", "--app", "sample")
    configuration = describe["result"]["configuration"]
    expected_store = "PostgresVectorStore" if args.postgres else "SQLiteVectorStore"
    assert configuration["retrieval"]["store"] == expected_store
    if args.process:
        assert configuration["ingestion"]["implementation"] == "pipeline"
        assert configuration["ingestion"]["stages"] == [
            "read",
            "parse",
            "normalize",
            "label",
            "prepare",
            "publish",
        ]
    else:
        assert configuration["ingestion"]["implementation"] == "builtin"
        assert configuration["ingestion"]["permissions"] == {"read": ["*"], "write": ["*"]}
        assert set(configuration["defaults_applied"]) >= {
            "parser",
            "ingestion",
            "readers",
            "retrieval",
        }
    assert "write" not in describe["result"]["operations"]
    phrase = "몸이 좋지 않을 때 누구를 찾아가야 하나요?"
    lexical = host.command(
        "call", "search", "--app", "sample", "--mode", "lexical", "--query", phrase
    )
    vector = host.command(
        "call", "search", "--app", "sample", "--mode", "vector", "--query", phrase
    )
    assert lexical == {"ok": True, "result": []}
    assert vector["ok"] and vector["result"][0]["metadata"]["name"] == "clinic.md"
    if args.process:
        assert vector["result"][0]["metadata"]["pipeline"] == "sample"
    key = vector["result"][0]["key"]
    provisioned = provision(host, vector["result"])
    question = phrase + " 예약 확인 번호도 알려주세요."
    cases = {}
    for role in ("member", "administrator", "root"):
        output = args.output / role
        answer = query(host, role, question, output)
        cases[role] = (
            check(output, answer, forbidden=(code,))
            if role == "administrator"
            else check(output, answer, expected_key=key, required=(code,))
        )
    before = host.authenticated_command("operator", "call", "index_status", "--app", "sample")
    host.command("group-remove", "team", "member")
    after = host.authenticated_command("operator", "call", "index_status", "--app", "sample")
    assert before == after, "Membership changes created indexing work"
    removed = args.output / "removed_member"
    answer = query(host, "member", question, removed)
    cases["removed_member"] = check(removed, answer, forbidden=(code,))
    result = {
        "passed": True,
        "preset": "process" if args.process else "default",
        "project": host.project,
        "storage": expected_store,
        "namespace": namespace,
        "sync": sync,
        "describe": describe,
        "lexical": lexical,
        "vector": vector,
        "directory": provisioned,
        "indexing_unchanged_after_membership_removal": True,
        "cases": cases,
    }
    (args.output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"passed": True, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
