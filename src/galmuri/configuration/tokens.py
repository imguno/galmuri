"""Publish complete host credentials atomically without replacing an existing token."""

import os
import secrets
import tempfile
from pathlib import Path


def load_or_create_token(path: Path) -> str:
    try:
        return _read(path)
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".admin-token-", dir=path.parent)
    candidate = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Linking a complete private file is atomic and cannot clobber a winner.
            os.link(candidate, path)
        except FileExistsError:
            pass
        else:
            if os.name == "posix":
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
    finally:
        candidate.unlink()
    return _read(path)


def _read(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("Admin token file must not be empty")
    return value
