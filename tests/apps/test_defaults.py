"""Beginner defaults resolve once and preserve explicit advanced composition."""

import sys
from dataclasses import replace

import pytest
from duru import ReadOnlyLocalProvider

from galmuri import App, Document, IngestResult, Principal
from galmuri.apps.resolution import resolve_app
from galmuri.configuration import load_project
from galmuri.ingestion import IngestConfig, IngestHandler
from galmuri.parsing import ParsingConfig, parse_text
from galmuri.retrieval import FastEmbedEmbedding, SQLiteVectorStore
from galmuri.runtime import Runtime


def source(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "hello.md").write_text("# private document", encoding="utf-8")
    return ReadOnlyLocalProvider(root)


def custom_parser(file):
    return (Document("custom", file.text.upper()),)


def test_source_only_defaults_are_actual_local_providers_without_inference(tmp_path, monkeypatch):
    def no_inference(self):
        pytest.fail("Resolving App defaults must not load model weights")

    monkeypatch.setattr(FastEmbedEmbedding, "_load", no_inference)
    monkeypatch.setenv("EMBEDDING_CACHE", str(tmp_path / "cache"))
    provider = source(tmp_path)
    declared = App("knowledge", provider)
    app = resolve_app(declared, tmp_path / "runtime" / "state.db")
    assert app.source.provider is provider
    assert isinstance(app.handler, IngestHandler)
    assert app.handler.config.readers == ("*",)
    assert app.handler.config.writers == ("*",)
    assert isinstance(app.retrieval.embedding, FastEmbedEmbedding)
    assert app.retrieval.embedding._model is None
    assert app.retrieval.embedding.cache_dir == str(tmp_path / "cache")
    assert isinstance(app.retrieval.store, SQLiteVectorStore)
    assert app.retrieval.store.identity.endswith("runtime/vectors.sqlite3")
    assert app.retrieval.mode == "hybrid"
    repeated = resolve_app(app, tmp_path / "runtime" / "state.db")
    assert repeated.revision == app.revision
    assert repeated.retrieval.fingerprint == app.retrieval.fingerprint


def test_explicit_retrieval_does_not_construct_an_unused_backend_default_store(tmp_path):
    from galmuri.apps.resolution import resolve_apps

    def unused(app):
        pytest.fail("Explicit retrieval must not create a default vector store")

    apps = [App("docs", source(tmp_path), retrieval=None)]
    assert resolve_apps(apps, tmp_path / "state.db", store_factory=unused)[0].retrieval is None


def test_default_grants_allow_access_without_inventing_a_user_identity(tmp_path):
    runtime = Runtime(tmp_path / "state.db", [App("docs", source(tmp_path), retrieval=None)])
    runtime.sync()
    assert runtime.search("docs", "private", Principal("local"))
    assert runtime.search("docs", "private", Principal())
    assert runtime.search("docs", "private", Principal("admin", administrator=True))
    assert runtime.apps["docs"].handler.config.writers == ("*",)


@pytest.mark.parametrize("readers,allowed", [((), False), (("*",), True)])
def test_explicit_reader_collection_is_not_replaced_by_default(tmp_path, readers, allowed):
    runtime = Runtime(
        tmp_path / "state.db",
        [App("docs", source(tmp_path), ingestion=IngestConfig(readers=readers), retrieval=None)],
    )
    runtime.sync()
    assert runtime.apps["docs"].handler.config.readers == readers
    assert bool(runtime.search("docs", "private", Principal())) is allowed
    assert bool(runtime.search("docs", "private", Principal("local"))) is allowed
    assert (
        bool(runtime.search("docs", "private", Principal("admin", administrator=True))) is allowed
    )


def test_ordinary_parser_and_explicit_lexical_override(tmp_path):
    runtime = Runtime(
        tmp_path / "state.db",
        [App("docs", source(tmp_path), parser=custom_parser, retrieval=None)],
    )
    runtime.sync()
    app = runtime.apps["docs"]
    assert app.retrieval is None
    assert app.handler.parsing.identity.endswith(":custom_parser")
    assert runtime.read("docs", "custom", Principal("local"))["text"] == "# PRIVATE DOCUMENT"


def test_explicit_handler_keeps_existing_lexical_behavior(tmp_path):
    def handler(file):
        return IngestResult((Document("explicit", file.text, readers=("*",)),))

    declared = App("docs", source(tmp_path), handler)
    runtime = Runtime(tmp_path / "state.db", [declared])
    runtime.sync()
    assert runtime.apps["docs"].revision == "1"
    assert runtime.apps["docs"].handler is handler
    assert runtime.apps["docs"].retrieval is None
    assert runtime.read("docs", "explicit", Principal())["text"] == "# private document"


def test_parser_revision_requires_activation_and_changes_only_ingestion_revision(tmp_path):
    declared = App(
        "docs", source(tmp_path), parser=ParsingConfig(parse_text, revision="1"), retrieval=None
    )
    old = Runtime(tmp_path / "state.db", [declared])
    old.collect("docs")
    revised = replace(declared, parser=ParsingConfig(parse_text, revision="2"))
    with pytest.raises(ValueError, match="explicit activate"):
        Runtime(tmp_path / "state.db", [revised])
    current = Runtime(tmp_path / "state.db", [revised], activate=True)
    assert old.work_once() is False
    assert current.apps["docs"].revision != old.apps["docs"].revision
    current.sync()
    assert current.search("docs", "private", Principal("local"))
    assert resolve_app(
        replace(current.apps["docs"], revision="2"), tmp_path / "state.db"
    ).revision.startswith("2@ingest:")


def test_ingestion_grants_are_part_of_activation_identity(tmp_path):
    declared = App("docs", source(tmp_path), retrieval=None)
    private = Runtime(tmp_path / "state.db", [declared])
    public = replace(declared, ingestion=IngestConfig(readers=()))
    with pytest.raises(ValueError, match="explicit activate"):
        Runtime(tmp_path / "state.db", [public])
    activated = Runtime(tmp_path / "state.db", [public], activate=True)
    assert activated.apps["docs"].revision != private.apps["docs"].revision


def test_store_switch_does_not_change_ingestion_revision(tmp_path):
    app = resolve_app(App("docs", source(tmp_path)), tmp_path / "state.db")
    changed = replace(
        app, retrieval=replace(app.retrieval, store=SQLiteVectorStore(tmp_path / "other.db"))
    )
    replacement = resolve_app(changed, tmp_path / "state.db")
    assert replacement.revision == app.revision
    assert replacement.retrieval.fingerprint != app.retrieval.fingerprint


def test_direct_ingest_handler_configuration_is_preserved(tmp_path):
    handler = IngestHandler(ParsingConfig(custom_parser), IngestConfig(readers=("*",), writers=()))
    resolved = resolve_app(App("docs", source(tmp_path), handler), tmp_path / "state.db")
    assert resolved.handler.parsing.parser is custom_parser
    assert resolved.handler.config.readers == ("*",)
    repeated = resolve_app(resolved, tmp_path / "state.db")
    assert repeated.handler.parsing.parser is custom_parser
    assert repeated.handler.config.readers == ("*",)
    assert repeated.revision == resolved.revision


def test_restarting_resolved_runtime_preserves_configured_fallback_policy(tmp_path):
    original = Runtime(
        tmp_path / "state.db",
        [App("docs", source(tmp_path), retrieval=None)],
        default_permissions={"read": ["group:team"], "write": []},
    )
    restarted = Runtime(tmp_path / "state.db", list(original.apps.values()))
    assert restarted.apps["docs"].handler.config.readers == ("group:team",)
    assert restarted.apps["docs"].handler.config.writers == ()
    assert restarted.apps["docs"].revision == original.apps["docs"].revision


def test_old_owner_setting_has_no_effect_and_defaults_are_independent_from_caller(tmp_path):
    root = tmp_path / "workspace"
    (root / "config").mkdir(parents=True)
    (root / "config/settings.py").write_text(
        "from galmuri import App, Principal\n"
        "from duru import ReadOnlyLocalProvider\n"
        "from pathlib import Path\n"
        "DATABASE = '.runtime/state.db'\n"
        "DOCUMENT_OWNER = Principal('owner')\n"
        "LOCAL_PRINCIPAL = Principal('caller')\n"
        "APPS = [App('docs', ReadOnlyLocalProvider(Path(__file__).parents[1]), retrieval=None)]\n",
        encoding="utf-8",
    )
    project = load_project(root)
    runtime = project.runtime()
    assert runtime.apps["docs"].handler.config.readers == ("*",)
    assert project.principal.subject == "caller"
    assert project.apps[0].revision == runtime.apps["docs"].revision
    settings = next(
        module
        for module in sys.modules.values()
        if getattr(module, "__file__", None) == str(root / "config/settings.py")
    )
    settings.LOCAL_PRINCIPAL = Principal("different")
    changed = load_project(root)
    assert changed.apps[0].revision == project.apps[0].revision
    assert changed.runtime().apps["docs"].handler.config.readers == ("*",)


def test_ambiguous_custom_handler_and_parser_are_rejected(tmp_path):
    app = App("docs", source(tmp_path), lambda file: IngestResult(()), parser=custom_parser)
    with pytest.raises(ValueError, match="omit the custom handler"):
        resolve_app(app, tmp_path / "state.db")


def test_owner_runtime_api_is_removed(tmp_path):
    with pytest.raises(TypeError, match="owner"):
        Runtime(tmp_path / "state.db", [], owner=Principal("alice"))


def test_settings_fallback_denies_but_explicit_app_policy_can_allow(tmp_path):
    runtime = Runtime(
        tmp_path / "state.db",
        [App("docs", source(tmp_path), retrieval=None)],
        default_permissions={"read": [], "write": []},
    )
    runtime.sync()
    assert runtime.search("docs", "private", Principal("admin", administrator=True)) == []
    revised = replace(runtime.apps["docs"], ingestion=IngestConfig(readers=("*",)))
    activated = Runtime(tmp_path / "state.db", [revised], activate=True)
    activated.sync()
    assert activated.search("docs", "private", Principal())
