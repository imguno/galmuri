import hashlib
import io
from dataclasses import replace

import pytest
from duru import (
    ConditionalWritable,
    Conflict,
    Listable,
    LocalProvider,
    NotFound,
    Page,
    Provider,
    ResourceInfo,
)

from galmuri import App, Principal
from galmuri.collection.policies import SyncPolicy
from galmuri.contracts.files import EffectUnknown
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto
from galmuri.runtime import Runtime
from galmuri.sources.resources import ReadOnlyResources, Resources


class OpaqueProvider(Provider, Listable):
    identity = "account:one"
    root_uri = "opaque:collection-id"
    item_uri = "opaque:123456"

    def __init__(self):
        self.name = "guide.md"
        self.content = b"# Welcome\nexternal resource"
        self.present = True
        self.streams = []
        self.after_open = lambda: None

    def stat(self, uri):
        if uri == self.root_uri:
            return ResourceInfo(uri, "Documents", kind="collection")
        if uri != self.item_uri or not self.present:
            raise NotFound("Absent")
        return ResourceInfo(
            uri,
            self.name,
            revision=hashlib.sha256(self.content).hexdigest(),
            metadata={"provider_field": "retained"},
        )

    def open(self, uri, *, expected_revision=None):
        info = self.stat(uri)
        if expected_revision is not None and expected_revision != info.revision:
            raise Conflict("Changed")
        stream = io.BytesIO(self.content)
        self.streams.append(stream)
        self.after_open()
        return stream

    def list(self, uri, *, cursor=None, limit=100):
        return Page((self.stat(self.item_uri),) if self.present else ())


class WritableOpaqueProvider(OpaqueProvider, ConditionalWritable):
    def write(self, uri, content, *, expected_revision=None):
        info = self.stat(uri)
        if expected_revision != info.revision:
            raise Conflict("Changed")
        self.content = content
        return self.stat(uri)


def prepare(file):
    readers = ("group:dev",) if ".dev." in file.name else ("*",)
    return index_default(parse_auto(file), readers=readers, writers=("group:dev",))


def test_opaque_uri_uses_explicit_name_for_parser_and_survives_serialization(tmp_path):
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)
    assert not callable(getattr(source, "write", None))
    runtime = Runtime(tmp_path / "state.db", [App("external", source, prepare)])
    runtime.sync()
    doc = runtime.read("external", provider.item_uri, Principal())
    assert doc["metadata"]["format"] == "markdown"
    assert doc["metadata"]["name"] == "guide.md"
    assert all(stream.closed for stream in provider.streams)
    restarted = Runtime(runtime.database.path, list(runtime.apps.values()))
    assert restarted.search("external", "external", Principal())


def test_name_change_reprocesses_same_content_and_replaces_document_permissions(tmp_path):
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)
    runtime = Runtime(tmp_path / "state.db", [App("external", source, prepare)])
    runtime.sync()
    previous = source.current(provider.item_uri)
    provider.name = "guide.dev.md"
    assert source.current(provider.item_uri).version != previous.version
    runtime.sync()
    assert runtime.search("external", "external", Principal()) == []
    assert runtime.search("external", "external", Principal("dev", frozenset({"dev"})))


def test_description_change_during_read_fails_and_closes_stream():
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)
    ref = source.scan()[0]
    provider.after_open = lambda: setattr(provider, "name", "changed.dev.md")
    with pytest.raises(Conflict):
        source.read(ref)
    assert provider.streams[-1].closed


def test_failed_stream_read_also_closes_stream():
    class Failing(io.BytesIO):
        def read(self, *args):
            raise OSError("remote interrupted")

    provider = OpaqueProvider()
    stream = Failing()
    source = Resources(provider, provider.root_uri)
    ref = source.scan()[0]
    provider.open = lambda *args, **kwargs: stream
    with pytest.raises(OSError):
        source.read(ref)
    assert stream.closed


def test_collection_cycles_are_safe_and_repeated_cursors_fail_explicitly():
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)
    provider.list = lambda *args, **kwargs: Page((provider.stat(provider.root_uri),))
    assert source.scan() == ()
    provider.list = lambda *args, **kwargs: Page((), "same-cursor")
    with pytest.raises(ValueError, match="cursor"):
        source.scan()


def test_paginated_scan_preserves_opaque_names_and_never_reports_partial_success():
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)

    def pages(uri, *, cursor=None, limit=100):
        if cursor is None:
            return Page((provider.stat(provider.item_uri),), "opaque-next")
        raise PermissionError("next page denied")

    provider.list = pages
    with pytest.raises(PermissionError):
        source.scan()


def test_missing_listing_entry_is_not_a_deletion(tmp_path):
    provider = OpaqueProvider()
    runtime = Runtime(
        tmp_path / "state.db", [App("external", Resources(provider, provider.root_uri), prepare)]
    )
    runtime.sync()
    # A partial listing does not prove disappearance while stat still resolves it.
    provider.list = lambda *args, **kwargs: Page(())
    runtime.sync()
    assert runtime.search("external", "external", Principal())
    # The snapshot bridge can withdraw it only after authoritative NotFound.
    provider.present = False
    runtime.sync()
    assert runtime.search("external", "external", Principal()) == []


def test_snapshot_does_not_turn_denied_stat_into_a_tombstone():
    provider = OpaqueProvider()
    source = Resources(provider, provider.root_uri)
    first = source.changes(None)
    provider.list = lambda *args, **kwargs: Page(())
    provider.stat = lambda uri: (_ for _ in ()).throw(PermissionError("denied"))
    with pytest.raises(PermissionError):
        source.changes(first.checkpoint)


def test_only_conditional_provider_writes_are_exposed_and_receipts_reindex(tmp_path):
    provider = WritableOpaqueProvider()
    source = Resources(provider, provider.root_uri)
    runtime = Runtime(tmp_path / "state.db", [App("external", source, prepare)])
    runtime.sync()
    dev = Principal("developer", frozenset({"dev"}))
    version = source.current(provider.item_uri).version
    receipt = runtime.write("external", provider.item_uri, "replacement", dev, version)
    assert receipt["state"] == "SUCCEEDED"
    runtime.drain()
    assert runtime.read("external", provider.item_uri, dev)["text"] == "replacement"
    with pytest.raises(Conflict):
        source.write(provider.item_uri, b"stale", version)


def test_unversioned_and_nonserializable_resources_fail_at_bridge_boundary():
    provider = OpaqueProvider()
    info = provider.stat(provider.item_uri)
    source = Resources(provider, provider.item_uri)
    provider.stat = lambda uri: replace(info, revision=None)
    with pytest.raises(ValueError, match="revision"):
        source.scan()
    provider.stat = lambda uri: replace(info, metadata={"bad": object()})
    with pytest.raises(TypeError):
        source.scan()


def test_bad_write_receipt_requires_reconciliation_and_blocks_another_write(tmp_path):
    provider = WritableOpaqueProvider()
    source = Resources(provider, provider.root_uri)
    runtime = Runtime(tmp_path / "state.db", [App("external", source, prepare)])
    runtime.sync()
    original_write = provider.write

    def corrupt_receipt(*args, **kwargs):
        return replace(original_write(*args, **kwargs), uri="opaque:wrong-id")

    provider.write = corrupt_receipt
    dev = Principal("developer", frozenset({"dev"}))
    version = source.current(provider.item_uri).version
    with pytest.raises(EffectUnknown):
        runtime.write("external", provider.item_uri, "applied", dev, version)
    assert provider.content == b"applied"
    assert runtime.status()["writes"][0]["state"] == "RECONCILING"
    with pytest.raises(EffectUnknown):
        runtime.write("external", provider.item_uri, "must not run", dev, version)
    assert provider.content == b"applied"


def test_app_schedule_remains_app_owned_and_explicit_readonly_wrapper_hides_writes(tmp_path):
    provider = LocalProvider(tmp_path)
    (tmp_path / "file.md").write_bytes(b"local provider")
    source = ReadOnlyResources(provider, provider.root_uri)
    assert not hasattr(source, "write")
    app = App("sample", source, prepare, SyncPolicy(mode="scan", interval=86400))
    assert app.policy.interval == 86400
    assert source.read(source.scan()[0]).content == b"local provider"
