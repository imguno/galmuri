"""Provider IO bridge; app policy owns discovery timing and durable retries."""

import hashlib

from duru import ConditionalWritable, Listable, Provider

from galmuri.contracts.files import (
    Change,
    ChangeSet,
    EffectUnknown,
    File,
    FileRef,
    SourceConflict,
)
from galmuri.ingestion.sources.references import reference
from galmuri.ingestion.sources.snapshots import Snapshots


class ReadOnlyResources:
    def __init__(self, provider: Provider, root_uri: str, *, recursive: bool = True) -> None:
        if not isinstance(provider, Provider):
            raise TypeError("Resource sources require a duru.Provider")
        if not isinstance(root_uri, str) or not root_uri:
            raise ValueError("A nonempty resource root URI is required")
        self.provider, self.root_uri, self.recursive = provider, root_uri, recursive
        self._snapshots = Snapshots(self.identity)

    discovery_method = "snapshot_scan"

    @property
    def identity(self) -> str:
        # Account/workspace identity belongs to the provider; credentials do not.
        root = hashlib.sha256(self.root_uri.encode("utf-8")).hexdigest()
        return f"resources:{self.provider.identity}:{root}"

    def current(self, key: str) -> FileRef:
        return reference(self.provider.stat(key))

    def read(self, ref: FileRef) -> File:
        current = self.current(ref.key)
        if current.key != ref.key or current.version != ref.version:
            raise SourceConflict("Resource changed before reading")
        with self.provider.open(
            ref.key, expected_revision=current.metadata["resource_revision"]
        ) as stream:
            content = stream.read()
        if not isinstance(content, bytes):
            raise TypeError("Resource streams must return bytes")
        after = self.current(ref.key)
        if after.key != ref.key or after.version != ref.version:
            raise SourceConflict("Resource description changed while reading")
        return File(current, content)

    def scan(self) -> tuple[FileRef, ...]:
        pending = [self.root_uri]
        visited: set[str] = set()
        references: dict[str, FileRef] = {}
        while pending:
            uri = pending.pop()
            if uri in visited:
                continue
            visited.add(uri)
            info = self.provider.stat(uri)
            if info.kind == "file":
                references[info.uri] = reference(info)
                continue
            if not isinstance(self.provider, Listable):
                raise TypeError("Collection processing requires Listable")
            cursor = None
            seen_cursors: set[str] = set()
            while True:
                page = self.provider.list(info.uri, cursor=cursor)
                for item in page.items:
                    if item.kind == "file":
                        references[item.uri] = reference(item)
                    elif self.recursive:
                        pending.append(item.uri)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if not cursor or cursor in seen_cursors:
                    raise ValueError("Provider repeated an invalid pagination cursor")
                seen_cursors.add(cursor)
        return tuple(references.values())

    def changes(self, checkpoint: str | None) -> ChangeSet:
        """Compare observations; confirm missing URIs through the provider's stat.

        This is a full snapshot scan, not a vendor delta API. A listing omission
        alone never proves deletion and an authorization error never becomes one.
        """
        previous = self._snapshots.load(checkpoint)
        current = {ref.key: ref for ref in self.scan()}
        changes = [
            Change(ref)
            for key, ref in current.items()
            if key not in previous or previous[key].version != ref.version
        ]
        for key, old in previous.items():
            if key in current:
                continue
            try:
                info = self.provider.stat(key)
                ref = reference(info) if info.kind == "file" else None
            except FileNotFoundError:
                ref = None
            if ref is None:
                changes.append(Change(old, deleted=True))
            else:
                current[key] = ref
                if ref.version != old.version:
                    changes.append(Change(ref))
        return ChangeSet(tuple(changes), self._snapshots.dump(current))


class Resources(ReadOnlyResources):
    """Expose source writes only for providers guaranteeing conditional replacement."""

    def __new__(cls, provider: Provider, root_uri: str, *, recursive: bool = True):
        if cls is Resources and not isinstance(provider, ConditionalWritable):
            return ReadOnlyResources(provider, root_uri, recursive=recursive)
        return super().__new__(cls)

    def write(self, key: str, content: bytes, expected_version: str) -> FileRef:
        current = self.current(key)
        if current.key != key or current.version != expected_version:
            raise SourceConflict("Resource changed before writing")
        info = self.provider.write(
            key, content, expected_revision=current.metadata["resource_revision"]
        )
        if info.uri != key:
            raise EffectUnknown("Resource write returned a different identity after mutation")
        return reference(info)
