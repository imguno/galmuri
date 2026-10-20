"""Own generation state and preserve files that the generator did not create."""

import json
import keyword
import os
import re
import stat
from pathlib import Path
from typing import TextIO

_RESERVED = {
    "apps",
    "config",
    "galmuri",
    "duru",
    "manage",
    "__init__",
    "__pycache__",
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def validate_name(name: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        or not name.strip("_")
        or keyword.iskeyword(name)
        or name.lower() in _RESERVED
    ):
        raise ValueError(f"Invalid name {name!r}: use a non-reserved Python identifier")


def checked_path(path: str | Path) -> Path:
    """Check links before resolving; even a dangling link is an existing target."""
    target = Path(path).absolute()
    for parent in (target, *target.parents):
        if parent.is_symlink() or parent.is_junction():
            raise FileExistsError(f"Refusing a symbolic link or junction: {parent}")
    return target.resolve()


def require_complete(path: Path) -> None:
    """Hand-written trees have no manifest; generated trees must be complete."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        complete = manifest.get("schema") == 1 and manifest.get("state") == "COMPLETE"
    except (OSError, ValueError, AttributeError):
        complete = False
    if not complete:
        raise ValueError(f"Incomplete generation at {path.parent}; inspect {path.name}")


def _state(stream: TextIO, state: str) -> None:
    stream.seek(0)
    stream.write(json.dumps({"schema": 1, "state": state}) + "\n")
    stream.truncate()
    stream.flush()


def _same_entry(path: Path, created: os.stat_result) -> bool:
    current = path.lstat()
    return (
        current.st_ino == created.st_ino
        and current.st_dev == created.st_dev
        and stat.S_IFMT(current.st_mode) == stat.S_IFMT(created.st_mode)
    )


def _same_parents(path: Path, directories: dict[Path, os.stat_result]) -> bool:
    return all(
        _same_entry(parent, created)
        for parent, created in directories.items()
        if parent in path.parents
    )


def write_tree(path: str | Path, contents: dict[str, str], *, manifest_name: str) -> Path:
    """Create exclusively, complete last, and roll back unchanged owned output on error."""
    target = checked_path(path)
    target.mkdir(parents=True, exist_ok=False)
    manifest = target / manifest_name
    files: list[tuple[Path, os.stat_result, bytes]] = []
    directories: dict[Path, os.stat_result] = {target: target.stat()}
    # Keep the manifest handle for the transaction; never overwrite another writer's entry.
    with manifest.open("x", encoding="utf-8", newline="\n") as state_stream:
        try:
            _state(state_stream, "PREPARING")
            for relative, content in contents.items():
                output = target / relative
                parents = [target]
                parent = output.parent
                while parent != target:
                    parents.insert(1, parent)
                    parent = parent.parent
                for directory in parents:
                    if directory in directories:
                        if not _same_entry(directory, directories[directory]):
                            raise FileExistsError(f"Generation directory changed: {directory}")
                        continue
                    # Never adopt a directory created by another writer.
                    directory.mkdir()
                    directories[directory] = directory.stat()
                with output.open("x", encoding="utf-8", newline="\n") as stream:
                    files.append((output, os.fstat(stream.fileno()), content.encode("utf-8")))
                    stream.write(content)
            _state(state_stream, "COMPLETE")
        except BaseException as error:
            for output, created, expected in reversed(files):
                try:
                    if (
                        _same_parents(output, directories)
                        and _same_entry(output, created)
                        and output.read_bytes() == expected
                    ):
                        output.unlink()
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    error.add_note(f"Could not remove generated file {output}: {cleanup_error}")
            for directory, created in reversed(directories.items()):
                try:
                    if (
                        directory != target
                        and _same_parents(directory, directories)
                        and _same_entry(directory, created)
                    ):
                        directory.rmdir()
                except OSError:
                    # Leave concurrent files and any directory containing them intact.
                    pass
            try:
                _state(state_stream, "FAILED")
            except OSError as state_error:
                error.add_note(f"Could not record FAILED at {manifest}: {state_error}")
            raise
    return target
