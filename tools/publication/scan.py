"""Read the exact Git index; optional workspace inventory reads names only."""

import os
import subprocess
from pathlib import Path

from tools.publication.patterns import content_findings, private_path


def _git(repository, *arguments, input=None):
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments], input=input, capture_output=True
    )
    if result.returncode:
        raise RuntimeError("Git publication inputs could not be read")
    return result.stdout


def scan_staged(repository):
    repository = Path(repository).resolve()
    index = _git(repository, "ls-files", "--stage", "-z")
    entries, findings = [], []
    for record in index.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_id, stage = metadata.split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if stage != b"0":
            findings.append({"kind": "unmerged_index", "path": path, "line": 0})
            continue
        kind = private_path(path)
        if kind:
            findings.append({"kind": kind, "path": path, "line": 0})
        if mode == b"160000":
            findings.append({"kind": "unscanned_submodule", "path": path, "line": 0})
            continue
        if mode == b"120000":
            findings.append({"kind": "unreviewed_symlink", "path": path, "line": 0})
        entries.append((path, object_id))
    payload = _git(
        repository, "cat-file", "--batch", input=b"".join(sha + b"\n" for _, sha in entries)
    )
    offset = 0
    for path, _ in entries:
        boundary = payload.find(b"\n", offset)
        if boundary < 0:
            raise RuntimeError("Git blob response was incomplete")
        header = payload[offset:boundary].split()
        if len(header) != 3 or header[1] != b"blob":
            raise RuntimeError("Git index contained an unreadable blob")
        size = int(header[2])
        offset = boundary + 1
        content = payload[offset : offset + size]
        if len(content) != size:
            raise RuntimeError("Git blob response was incomplete")
        findings.extend(content_findings(path, content))
        offset += size + 1
    return {"scope": "staged_git_index", "checked_files": len(entries), "findings": findings}


def inventory_workspace(workspace):
    """Inventory private/work paths without opening them or following symlinks."""
    root = Path(workspace).resolve()
    skipped = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "target",
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "models",
        "node_models",
    }
    findings = []
    for directory, directories, files in os.walk(root, followlinks=False):
        current = Path(directory)
        retained = []
        for name in directories:
            path = current / name
            relative = path.relative_to(root).as_posix()
            if name.casefold() in skipped or path.is_symlink():
                continue
            kind = private_path(relative)
            if name == "docs" and current == root:
                kind = "workspace_internal_documentation"
            if kind:
                findings.append({"kind": kind, "path": relative + "/", "line": 0})
            else:
                retained.append(name)
        directories[:] = retained
        for name in files:
            relative = (current / name).relative_to(root).as_posix()
            kind = private_path(relative)
            if kind:
                findings.append({"kind": kind, "path": relative, "line": 0})
    return findings
