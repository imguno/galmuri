"""The only public documents admitted under a docs directory."""

from pathlib import PurePosixPath

PUBLIC_DOCUMENTS = (
    "CONTRIBUTING.md",
    "CONTRIBUTING.ko.md",
    "SECURITY.md",
    "SECURITY.ko.md",
    "RELEASE.md",
    "RELEASE.ko.md",
)


def private_document_path(path):
    value = PurePosixPath(path)
    if value.name.casefold() in {"agent.md", "agents.md"} or value.name.casefold().startswith(
        "changelog"
    ):
        return True
    parts = value.parts
    for index, part in enumerate(parts):
        if part.casefold() == "docs":
            tail = parts[index + 1 :]
            return bool(tail) and (len(tail) != 1 or tail[0] not in PUBLIC_DOCUMENTS)
    return False
