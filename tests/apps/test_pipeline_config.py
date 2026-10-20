"""Grouped declarations preserve defaults, explicit choices and lifecycle identities."""

from dataclasses import FrozenInstanceError, replace

import pytest
from duru import ReadOnlyLocalProvider

from galmuri import (
    App,
    DatabaseConfig,
    Document,
    IngestConfig,
    IngestResult,
    ParsingConfig,
    Principal,
    RetrievalConfig,
)
from galmuri.apps.resolution import resolve_app
from galmuri.retrieval import FastEmbedEmbedding, SQLiteVectorStore
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import Embedding, Store


def source(tmp_path):
    directory = tmp_path / "files"
    directory.mkdir(exist_ok=True)
    (directory / "welcome.txt").write_text("welcome to grouped configuration", encoding="utf-8")
    return ReadOnlyLocalProvider(directory)


def named_parser(file):
    return (Document("custom", file.text.upper()),)


def custom_handler(file):
    return IngestResult((Document("custom", file.text, readers=("*",)),))


def forbidden(*args, **kwargs):
    pytest.fail("An explicit provider must not construct an unused default")


def test_empty_configs_match_implicit_default_revision_and_projection_identity(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(FastEmbedEmbedding, "_load", forbidden)
    provider = source(tmp_path)
    database = tmp_path / "state.db"
    implicit = resolve_app(App("docs", provider), database)
    explicit = resolve_app(
        App(
            "docs",
            provider,
            parser=ParsingConfig(),
            ingestion=IngestConfig(),
            retrieval=RetrievalConfig(),
            database=DatabaseConfig(),
        ),
        database,
    )
    assert explicit.revision == implicit.revision
    assert explicit.handler.fingerprint == implicit.handler.fingerprint
    assert explicit.handler.parsing.identity == "galmuri.parsing:auto:v2"
    assert explicit.retrieval.fingerprint == implicit.retrieval.fingerprint
    assert explicit.retrieval.mode == implicit.retrieval.mode == "hybrid"
    assert explicit.retrieval.embedding._model is None
    assert explicit.handler.config.readers == explicit.handler.config.writers == ("*",)


def test_partial_embedding_uses_only_selected_store_default(tmp_path, monkeypatch):
    import galmuri.retrieval

    monkeypatch.setattr(galmuri.retrieval, "FastEmbedEmbedding", forbidden)
    embedding, store, calls = Embedding(), Store(), []
    declaration = RetrievalConfig(embedding=embedding, batch_size=7)

    def select_store(app):
        calls.append(app.database.alias)
        return store

    app = resolve_app(
        App("docs", source(tmp_path), retrieval=declaration, database=DatabaseConfig("archive")),
        tmp_path / "state.db",
        store_factory=select_store,
    )
    assert calls == ["archive"]
    assert app.retrieval.embedding is embedding
    assert app.retrieval.store is store
    assert app.retrieval.batch_size == 7
    assert app.retrieval.mode == "hybrid"
    assert embedding.calls == 0
    assert declaration.store is None and declaration.mode is None


def test_partial_store_skips_backend_default_and_leaves_model_unloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(FastEmbedEmbedding, "_load", forbidden)
    store = Store()
    app = resolve_app(
        App("docs", source(tmp_path), retrieval=RetrievalConfig(store=store)),
        tmp_path / "state.db",
        store_factory=forbidden,
    )
    assert app.retrieval.store is store
    assert isinstance(app.retrieval.embedding, FastEmbedEmbedding)
    assert app.retrieval.embedding._model is None
    assert app.retrieval.mode == "hybrid"


def test_fully_explicit_retrieval_keeps_existing_vector_mode_without_default_construction(
    tmp_path, monkeypatch
):
    import galmuri.retrieval

    monkeypatch.setattr(galmuri.retrieval, "FastEmbedEmbedding", forbidden)
    config = RetrievalConfig(Embedding(), Store())
    app = resolve_app(
        App("docs", source(tmp_path), retrieval=config),
        tmp_path / "state.db",
        store_factory=forbidden,
    )
    assert app.retrieval.embedding is config.embedding
    assert app.retrieval.store is config.store
    assert app.retrieval.mode == "vector"
    assert app.retrieval.fingerprint == config.fingerprint


def test_shared_immutable_configs_resolve_without_cross_app_default_leakage(tmp_path):
    parsing, ingestion, retrieval = ParsingConfig(), IngestConfig(), RetrievalConfig()
    provider = source(tmp_path)
    left = resolve_app(
        App("left", provider, parser=parsing, ingestion=ingestion, retrieval=retrieval),
        tmp_path / "left" / "state.db",
        {"read": ["group:left"], "write": []},
    )
    right = resolve_app(
        App("right", provider, parser=parsing, ingestion=ingestion, retrieval=retrieval),
        tmp_path / "right" / "state.db",
        {"read": ["*"], "write": ["group:right"]},
    )
    assert ingestion.readers is ingestion.writers is None
    assert retrieval.embedding is retrieval.store is retrieval.mode is None
    assert left.handler.config.readers == ("group:left",)
    assert right.handler.config.readers == ("*",)
    assert left.retrieval.store.identity != right.retrieval.store.identity
    with pytest.raises(FrozenInstanceError):
        ingestion.revision = "2"
    customized = replace(ingestion, readers=())
    assert customized.readers == () and ingestion.readers is None
    assert replace(retrieval, batch_size=4).batch_size == 4


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("shared_cache", [False, True])
def test_rebinding_resolved_app_reselects_only_inherited_store(
    tmp_path, monkeypatch, partial, shared_cache
):
    monkeypatch.delenv("EMBEDDING_CACHE", raising=False)
    if shared_cache:
        monkeypatch.setenv("EMBEDDING_CACHE", str(tmp_path / "shared-models"))
    embedding = Embedding()
    original_store, replacement_store = Store(), Store()
    original_store.identity, replacement_store.identity = "original", "replacement"
    declaration = RetrievalConfig(embedding=embedding) if partial else RetrievalConfig()
    original = resolve_app(
        App("docs", source(tmp_path), retrieval=declaration),
        tmp_path / "one" / "state.db",
        store_factory=lambda app: original_store,
    )
    changed = replace(original, database=DatabaseConfig("archive", namespace="team"))
    rebound = resolve_app(
        changed,
        tmp_path / "two" / "state.db",
        store_factory=lambda app: replacement_store,
    )
    assert rebound.retrieval.store is replacement_store
    assert original.retrieval.store is original_store
    assert rebound.revision == original.revision
    assert rebound.retrieval.fingerprint != original.retrieval.fingerprint
    if partial:
        assert rebound.retrieval.embedding is embedding
    else:
        assert (
            rebound.retrieval.embedding.cache_dir == original.retrieval.embedding.cache_dir
        ) == shared_cache


def test_rebinding_preserves_explicit_store_and_explicit_effective_replacement(tmp_path):
    provider, embedding, store = source(tmp_path), Embedding(), Store()
    original = resolve_app(
        App("docs", provider, retrieval=RetrievalConfig(embedding=embedding, store=store)),
        tmp_path / "one" / "state.db",
        store_factory=forbidden,
    )
    changed = resolve_app(
        replace(original, database=DatabaseConfig("archive")),
        tmp_path / "two" / "state.db",
        store_factory=forbidden,
    )
    assert changed.retrieval.store is store
    assert changed.retrieval.embedding is embedding
    automatic = resolve_app(App("auto", provider), tmp_path / "one" / "state.db")
    replaced = replace(automatic, retrieval=replace(automatic.retrieval, store=store))
    resolved = resolve_app(replaced, tmp_path / "two" / "state.db", store_factory=forbidden)
    assert resolved.retrieval.store is store
    assert resolved.retrieval.embedding is automatic.retrieval.embedding


def test_explicit_deny_survives_grouped_defaults_and_runtime_restart(tmp_path):
    runtime = Runtime(
        tmp_path / "state.db",
        [
            App(
                "docs",
                source(tmp_path),
                ingestion=IngestConfig(readers=(), writers=()),
                retrieval=None,
            )
        ],
    )
    runtime.sync()
    restarted = Runtime(tmp_path / "state.db", list(runtime.apps.values()))
    assert restarted.apps["docs"].handler.config.readers == ()
    assert restarted.apps["docs"].handler.config.writers == ()
    assert restarted.search("docs", "welcome", Principal()) == []
    assert restarted.search("docs", "welcome", Principal("admin", administrator=True)) == []


@pytest.mark.parametrize(
    "invalid",
    [
        {"parser": {}},
        {"ingestion": {}},
        {"retrieval": {}},
        {"database": {}},
        {"parser": "auto"},
        {"ingestion": "default"},
        {"retrieval": "hybrid"},
    ],
)
def test_invalid_config_shapes_fail_before_source_binding(tmp_path, monkeypatch, invalid):
    import galmuri.ingestion.sources

    monkeypatch.setattr(galmuri.ingestion.sources, "bind", forbidden)
    with pytest.raises(TypeError):
        App("docs", object(), **invalid)
    assert not (tmp_path / "state.db").exists()


def test_raw_named_parser_normalizes_to_grouped_config(tmp_path):
    app = App("docs", source(tmp_path), parser=named_parser, retrieval=None)
    assert isinstance(app.parser, ParsingConfig)
    assert app.parser.parser is named_parser
    runtime = Runtime(tmp_path / "state.db", [app])
    runtime.sync()
    assert runtime.read("docs", "custom", Principal())["text"] == "WELCOME TO GROUPED CONFIGURATION"


def test_custom_handler_keeps_lexical_default_and_accepts_explicit_partial_retrieval(tmp_path):
    provider, embedding = source(tmp_path), Embedding()
    lexical = resolve_app(
        App("lexical", provider, custom_handler), tmp_path / "state.db", store_factory=forbidden
    )
    assert lexical.retrieval is None
    runtime = Runtime(
        tmp_path / "state.db",
        [App("semantic", provider, custom_handler, retrieval=RetrievalConfig(embedding=embedding))],
    )
    runtime.sync()
    assert runtime.search("semantic", "nonliteral", Principal(), mode="vector")
    assert runtime.apps["semantic"].retrieval.mode == "hybrid"
    assert embedding.calls == 1


def test_describe_reports_effective_grouped_providers_without_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(FastEmbedEmbedding, "_load", forbidden)
    runtime = Runtime(
        tmp_path / "state.db",
        [App("docs", source(tmp_path), parser=ParsingConfig(), retrieval=RetrievalConfig())],
    )
    selected = runtime.describe("docs", Principal())["configuration"]
    assert selected["ingestion"]["parser"]["identity"] == "galmuri.parsing:auto:v2"
    assert selected["retrieval"]["mode"] == "hybrid"
    assert selected["retrieval"]["embedding"]["provider"] == "fastembed"
    assert selected["retrieval"]["store"] == SQLiteVectorStore.__name__
    assert selected["retrieval"]["embedding"]["dimensions"] == 384


def test_partial_retrieval_fingerprint_requires_resolution():
    for config in (
        RetrievalConfig(),
        RetrievalConfig(embedding=Embedding()),
        RetrievalConfig(store=Store()),
    ):
        with pytest.raises(ValueError, match="Resolve retrieval defaults"):
            _ = config.fingerprint
