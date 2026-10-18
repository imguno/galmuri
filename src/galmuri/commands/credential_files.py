"""Publish a complete private credential file once; failed issuance is revoked."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def publish(store, credential, path):
    candidate = None
    published = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".credential-", dir=path.parent)
        candidate = Path(temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(credential["token"] + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # The final name never refers to an incomplete file; an existing name wins.
        os.link(candidate, path)
        published = True
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        if published:
            # Never remove a pre-existing or subsequently replaced operator file.
            with suppress(OSError):
                if os.path.samestat(candidate.stat(), path.stat(follow_symlinks=False)):
                    path.unlink()
        store.revoke_token(credential["id"])
        raise
    finally:
        if candidate is not None:
            with suppress(OSError):
                candidate.unlink()
    return {key: value for key, value in credential.items() if key != "token"} | {
        "token_file": str(path.resolve())
    }
