"""Run an authenticated external Codex client, recording actual model tool calls."""

import json
import shutil
import subprocess
from pathlib import Path

SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "document_key": {"type": ["string", "null"]},
    },
    "required": ["found", "answer", "document_key"],
    "additionalProperties": False,
}


def query(host, role: str, question: str, output: Path, *, timeout: int = 180):
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("Install and authenticate Codex CLI before live acceptance")
    output.mkdir()
    client_directory = output / "client"
    client_directory.mkdir()
    schema = output / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    answer = output / "answer.json"
    prompt = (
        "Act as a document reader using only the acceptance MCP server. "
        "First describe the source to learn search semantics, search relevant terms, "
        "and read any matching document before answering. Do not use shell, files, "
        "web, other servers, prior knowledge or guesses. Only return found=true if "
        "a successful read supports the answer; cite its exact document_key. "
        "If no visible document answers the question, return found=false and "
        "document_key=null and explain the absence. Preserve codes and location identifiers "
        "exactly as returned. Reply in Korean. Question: " + question
    )
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    options = {
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "mcp_servers.acceptance.command": "docker",
        "mcp_servers.acceptance.args": host.mcp_arguments(role),
        "mcp_servers.acceptance.enabled_tools": ["sample_describe", "sample_search", "sample_read"],
    }
    for name in ("sample_describe", "sample_search", "sample_read"):
        # This run permits only explicitly authorized readonly local test queries.
        options[f"mcp_servers.acceptance.tools.{name}.approval_mode"] = "auto"
    arguments = [
        executable,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--json",
        "--disable",
        "shell_tool",
        "--disable",
        "apps",
        "--disable",
        "multi_agent",
        "-C",
        str(client_directory),
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(answer),
    ]
    for key, value in options.items():
        arguments.extend(["-c", key + "=" + json.dumps(value, ensure_ascii=False)])
    # Prompt via stdin avoids shell quoting and OS command-line length limits.
    arguments.append("-")
    with (
        (output / "events.jsonl").open("w", encoding="utf-8") as events,
        (output / "stderr.log").open("w", encoding="utf-8") as errors,
    ):
        subprocess.run(
            arguments,
            input=prompt,
            stdout=events,
            stderr=errors,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=timeout,
            cwd=client_directory,
        )
    return json.loads(answer.read_text(encoding="utf-8"))
