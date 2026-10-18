"""Structural secret signatures and private artifact paths, not entropy guesses."""

import re
from pathlib import PurePosixPath

SIGNATURES = {
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "openai_token": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe_token": re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "credential_dsn": re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|rediss?)://"
        r"(?P<user>[^:/@\s\"'<>]+):(?P<password>[^/@\s\"'<>]+)@(?P<host>[^/\s\"'<>]+)",
        re.IGNORECASE,
    ),
}

PRIVATE_DIRECTORIES = frozenset(
    {".runtime", ".verification", ".venv", "node_modules", "__pycache__"}
)
WORK_DOC_DIRECTORIES = frozenset({"design", "decisions", "implementation", "research"})
PRIVATE_SUFFIXES = (".token", ".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".exe")


def private_path(path):
    value = PurePosixPath(path)
    parts = tuple(part.casefold() for part in value.parts)
    name = parts[-1] if parts else ""
    if any(part in PRIVATE_DIRECTORIES for part in parts):
        return "private_artifact_path"
    if any(
        left == "docs" and right in WORK_DOC_DIRECTORIES
        for left, right in zip(parts, parts[1:], strict=False)
    ):
        return "internal_documentation_path"
    if name == ".env" or name.startswith(".env.") and name not in {".env.example", ".env.template"}:
        return "credential_file_path"
    if name in {"id_rsa", "id_ecdsa", "id_ed25519"} or name.endswith(PRIVATE_SUFFIXES):
        return "credential_or_database_path"
    if name in {"credentials.json", "client_secret.json", "client-secret.json", "tokens.json"}:
        return "credential_file_path"
    if name.endswith(
        (".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")
    ):
        return "private_artifact_path"
    return None


def synthetic_dsn(match):
    """Documented disposable test credentials, never all credentials in tests/."""
    return (match.group("user"), match.group("password")) in {
        ("framework", "framework-test-only"),
        ("galmuri", "galmuri-test-only"),
    } and match.group("host").split(":", 1)[0] in {
        "127.0.0.1",
        "localhost",
        "framework-pg",
        "framework-process-pg",
        "framework-release-pg",
        "galmuri-release-pg",
    }


def content_findings(path, content):
    text = content.decode("utf-8", errors="replace")
    for line, value in enumerate(text.splitlines(), start=1):
        for kind, pattern in SIGNATURES.items():
            matches = tuple(pattern.finditer(value))
            if kind == "credential_dsn":
                matches = tuple(match for match in matches if not synthetic_dsn(match))
            if matches:
                yield {"kind": kind, "path": path, "line": line}
