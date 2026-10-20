"""App binds process references without calling them, including legacy replace."""

from dataclasses import replace

import pytest

from galmuri import App, Document, IngestResult
from galmuri.apps.resolution import resolve_app
from galmuri.ingestion.configuration import IngestConfig
from galmuri.ingestion.handler import IngestHandler
from galmuri.parsing import ParsingConfig, parse_auto
from galmuri.processing import Pipeline, process_default
from tests.ingestion.test_checkpoints import Source


def first(file):
    return IngestResult((Document("one", file.text),))


def second(file):
    return IngestResult((Document("two", file.text),))


def test_process_alias_is_a_reference_and_legacy_handler_still_works(tmp_path):
    source = Source()
    app = App("docs", source, process=first)
    assert app.process is app.handler is first
    assert source.reads == 0
    assert App("docs", source, first).process is first
    with pytest.raises(ValueError, match="different implementations"):
        App("docs", source, handler=first, process=second)
    for original in (app, resolve_app(app, tmp_path / "state.db")):
        assert replace(original, process=second).handler is second
        assert replace(original, handler=second).process is second


def test_default_process_reference_matches_source_only_defaults(tmp_path):
    source = Source()
    defaults = {"read": ("group:team",), "write": ()}
    explicit = resolve_app(
        App("docs", source, process=process_default), tmp_path / "state.db", defaults
    )
    automatic = resolve_app(App("docs", source), tmp_path / "state.db", defaults)
    assert explicit.handler.fingerprint == automatic.handler.fingerprint
    assert explicit.revision == automatic.revision
    assert explicit.retrieval is not None
    assert explicit.handler.config.readers == ("group:team",)


def test_pipeline_resolution_keeps_semantic_defaults_and_rebinds_global_grants(tmp_path):
    app = App("docs", Source(), process=Pipeline.default())
    resolved = resolve_app(app, tmp_path / "state.db", {"read": ("group:team",), "write": ()})
    assert resolved.retrieval is not None
    assert resolved.handler is resolved.process
    file = resolved.source.read(resolved.source.changes(None).changes[0].ref)
    assert resolved.process(file).documents[0].readers == ("group:team",)
    assert resolved.process(file).documents[0].writers == ()
    same = resolve_app(resolved, tmp_path / "state.db")
    assert same.revision == resolved.revision
    changed = resolve_app(resolved, tmp_path / "state.db", {"read": (), "write": ()})
    assert changed.revision != resolved.revision
    assert changed.process(file).documents[0].readers == ()


@pytest.mark.parametrize("field", ["process", "handler"])
@pytest.mark.parametrize("resolved", [False, True])
def test_reset_either_process_alias_reselects_all_automatic_defaults(tmp_path, field, resolved):
    def parse(file):
        return (Document("custom", file.text),)

    pipeline = Pipeline.default(
        parser=ParsingConfig(parse), ingestion=IngestConfig(readers=(), writers=())
    )
    app = App("docs", Source(), process=pipeline)
    if resolved:
        app = resolve_app(app, tmp_path / "state.db")
    reset = replace(app, **{field: None})
    assert reset.handler is reset.process is None
    rebound = resolve_app(reset, tmp_path / "state.db")
    assert isinstance(rebound.process, IngestHandler)
    assert rebound.process.parsing.process is parse_auto
    assert rebound.process.config.readers == rebound.process.config.writers == ("*",)
    assert rebound.retrieval is not None


@pytest.mark.parametrize("field", ["process", "handler"])
@pytest.mark.parametrize("resolved", [False, True])
@pytest.mark.parametrize("explicit_lexical", [False, True])
def test_reset_custom_function_recovers_requested_retrieval_default(
    tmp_path, field, resolved, explicit_lexical
):
    app = App("docs", Source(), process=first, **({"retrieval": None} if explicit_lexical else {}))
    if resolved:
        app = resolve_app(app, tmp_path / "state.db")
        assert app.retrieval is None
    reset = replace(app, **{field: None})
    assert reset.handler is reset.process is None
    rebound = resolve_app(reset, tmp_path / "state.db")
    assert isinstance(rebound.process, IngestHandler)
    assert (rebound.retrieval is None) is explicit_lexical


def test_explicit_legacy_ingest_handler_keeps_lexical_default_until_reset(tmp_path):
    explicit = IngestHandler(ParsingConfig(), IngestConfig(readers=("*",), writers=("*",)))
    app = resolve_app(App("docs", Source(), explicit), tmp_path / "state.db")
    assert app.retrieval is None
    reset = resolve_app(replace(app, process=None), tmp_path / "state.db")
    assert reset.retrieval is not None
