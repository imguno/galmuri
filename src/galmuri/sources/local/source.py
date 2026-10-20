"""Local source capabilities; discovery never parses document content."""

from pathlib import Path

from duru import LocalProvider, ReadOnlyLocalProvider

from galmuri.contracts.files import (
    Change,
    ChangeSet,
    File,
    FileRef,
)
from galmuri.sources.local.checkpoints import Snapshots


class ReadOnlyFiles:
    """A filesystem source without a write method or authorization policy.

    Checkpoints contain hashes, never file content. Hashing the tree detects
    modifications even when timestamps are preserved. External filesystem
    writers are detected, but must use their own atomic replacement discipline.
    """

    def __init__(self, root: Path) -> None:
        self.provider = ReadOnlyLocalProvider(root)
        self._tree = self.provider.tree
        self._snapshots = Snapshots(self._tree.root)

    @property
    def root(self) -> Path:
        return self._tree.root

    @property
    def identity(self) -> str:
        """Stable resource identity; changing roots must never inherit document grants."""
        return self.provider.identity

    def current(self, key: str) -> FileRef:
        info = self.provider.stat(self.provider.uri(key))
        return FileRef(key, info.revision, {"size": info.size})

    def read(self, ref: FileRef) -> File:
        with self.provider.open(
            self.provider.uri(ref.key), expected_revision=ref.version
        ) as stream:
            content = stream.read()
        return File(FileRef(ref.key, ref.version, {"size": len(content)}), content)

    def scan(self) -> tuple[FileRef, ...]:
        references = []
        for key in self._tree.keys():
            try:
                references.append(self.current(key))
            except FileNotFoundError:
                # Concurrent deletion is confirmed again by changes(), if known.
                continue
        return tuple(references)

    def changes(self, checkpoint: str | None) -> ChangeSet:
        previous = self._snapshots.load(checkpoint)
        current = {ref.key: ref for ref in self.scan()}
        changes = [
            Change(ref)
            for key, ref in current.items()
            if key not in previous or ref.version != previous[key].version
        ]
        for key, old_ref in previous.items():
            if key in current:
                continue
            try:
                # Absence in a mutable directory listing alone is not deletion.
                ref = self.current(key)
            except FileNotFoundError:
                changes.append(Change(old_ref, deleted=True))
            else:
                current[key] = ref
                if ref.version != old_ref.version:
                    changes.append(Change(ref))
        return ChangeSet(tuple(changes), self._snapshots.dump(current))


class LocalFiles(ReadOnlyFiles):
    """Version-conditional atomic writes in addition to read/discovery.

    Use ReadOnlyFiles when write exposure must be absent. The writable=False
    shortcut returns that same capability-restricted implementation.
    """

    def __new__(cls, root: Path, *, writable: bool = True):
        if not writable:
            return ReadOnlyFiles(root)
        return super().__new__(cls)

    def __init__(self, root: Path, *, writable: bool = True) -> None:
        super().__init__(root)
        self.provider = LocalProvider(root)
        self._tree = self.provider.tree

    def write(self, key: str, content: bytes, expected_version: str) -> FileRef:
        if not isinstance(content, bytes):
            raise TypeError("Source writes require bytes")
        if not expected_version:
            raise ValueError("Writes require an expected source version")
        info = self.provider.write(
            self.provider.uri(key), content, expected_revision=expected_version
        )
        return FileRef(key, info.revision, {"size": info.size})
