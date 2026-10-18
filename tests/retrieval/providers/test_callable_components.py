"""Function bindings preserve the existing bounded provider and artifact contracts."""

from dataclasses import FrozenInstanceError, replace
from itertools import repeat
from types import FunctionType

import pytest

from galmuri.retrieval import (
    CharacterChunker,
    Chunk,
    Chunker,
    ChunkingConfig,
    EmbeddingConfig,
    EmbeddingProvider,
    EmbeddingSpec,
    VectorValidationError,
)
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import DEV, fixture

SPEC = EmbeddingSpec("test-only", "deterministic-two", 2, "model-v1")


def encode_documents(texts):
    return ((1.0, 0.1) for _ in texts)


def encode_query(text):
    return (1.0, 0.1)


def alternate_query(text):
    return (0.1, 1.0)


def split_letters(text):
    return (Chunk(letter, index, index + 1) for index, letter in enumerate(text))


def split_whole(text):
    return (Chunk(text, 0, len(text)),)


def test_bindings_are_lazy_and_accept_arbitrarily_named_functions():
    calls = []

    def my_documents(texts):
        calls.append(texts)
        return encode_documents(texts)

    embedding = EmbeddingConfig(my_documents, encode_query, SPEC)
    chunker = ChunkingConfig(split_letters)
    assert isinstance(embedding, EmbeddingProvider)
    assert isinstance(chunker, Chunker)
    assert calls == []
    assert embedding.embed_documents(()) == ()
    assert calls == []
    assert embedding.embed_documents(("a", "b")) == ((1.0, 0.1), (1.0, 0.1))
    assert calls == [("a", "b")]
    assert embedding.embed_query("question") == (1.0, 0.1)
    assert tuple(chunker.split("가a")) == (Chunk("가", 0, 1), Chunk("a", 1, 2))
    assert embedding.declared_spec == SPEC
    assert embedding.spec.provider == SPEC.provider
    assert embedding.spec.model == SPEC.model
    assert embedding.spec.dimensions == SPEC.dimensions
    with pytest.raises(FrozenInstanceError):
        embedding.process = encode_documents


def test_adapter_identity_covers_each_callable_and_revision():
    base = EmbeddingConfig(encode_documents, encode_query, SPEC, identity="my-pair")
    assert (
        base.spec == EmbeddingConfig(encode_documents, encode_query, SPEC, identity="my-pair").spec
    )
    assert (
        base.spec
        != EmbeddingConfig(encode_documents, alternate_query, SPEC, identity="my-pair").spec
    )
    assert base.spec != EmbeddingConfig(encode_documents, encode_query, SPEC, revision="2").spec
    chunker = ChunkingConfig(split_letters)
    assert chunker.identity != ChunkingConfig(split_letters, revision="2").identity
    assert (
        ChunkingConfig(split_letters, identity="custom").identity
        != ChunkingConfig(split_whole, identity="custom").identity
    )


def test_binding_identities_are_portable_across_checkout_namespaces():
    def relocated(function, namespace):
        result = FunctionType(function.__code__, function.__globals__, function.__name__)
        result.__module__ = f"_workspace_{namespace}.sample.views"
        result.__qualname__ = function.__qualname__
        return result

    first, second = "0123456789abcdef", "fedcba9876543210"
    for identity in (None, "explicit"):
        assert ChunkingConfig(relocated(split_letters, first), identity=identity).identity == (
            ChunkingConfig(relocated(split_letters, second), identity=identity).identity
        )
        left = EmbeddingConfig(
            relocated(encode_documents, first),
            relocated(encode_query, first),
            SPEC,
            identity=identity,
        )
        right = EmbeddingConfig(
            relocated(encode_documents, second),
            relocated(encode_query, second),
            SPEC,
            identity=identity,
        )
        assert left.spec == right.spec


def test_explicit_instances_and_default_chunker():
    class Encoder:
        def documents(self, texts):
            return encode_documents(texts)

        def query(self, text):
            return encode_query(text)

    encoder = Encoder()
    with pytest.raises(ValueError, match="identity"):
        EmbeddingConfig(encoder.documents, encoder.query, SPEC)
    configured = EmbeddingConfig(encoder.documents, encoder.query, SPEC, identity="encoder:v1")
    assert configured.embed_query("q") == (1.0, 0.1)
    with pytest.raises(ValueError, match="identity"):
        ChunkingConfig(lambda text: ())
    assert ChunkingConfig(lambda text: (), identity="empty:v1").split("abc") == ()
    assert tuple(ChunkingConfig().split("abc")) == CharacterChunker().split("abc")
    assert tuple(ChunkingConfig.from_chunker(CharacterChunker(2, 0)).split("abc")) == (
        Chunk("ab", 0, 2),
        Chunk("c", 2, 3),
    )


def test_provider_adapter_is_lazy_and_preserves_model_metadata():
    class Provider:
        spec = SPEC

        def embed_documents(self, texts):
            return encode_documents(texts)

        def embed_query(self, text):
            return encode_query(text)

    configured = EmbeddingConfig.from_provider(Provider())
    assert configured.declared_spec == SPEC
    assert configured.embed_documents(("a",)) == ((1.0, 0.1),)


@pytest.mark.parametrize(
    "documents,query,spec",
    [
        (None, encode_query, SPEC),
        (encode_documents, None, SPEC),
        (encode_documents, encode_query, None),
    ],
)
def test_invalid_binding_rejected_before_execution(documents, query, spec):
    with pytest.raises(TypeError):
        EmbeddingConfig(documents, query, spec)


def test_bad_batches_and_vectors_are_bounded_and_rejected():
    infinite = EmbeddingConfig(
        lambda texts: repeat((1, 0)), encode_query, SPEC, identity="infinite"
    )
    with pytest.raises(VectorValidationError, match="batch length"):
        infinite.embed_documents(("one",))
    invalid = EmbeddingConfig(lambda texts: ((0, 0),), encode_query, SPEC, identity="invalid")
    with pytest.raises(VectorValidationError, match="zero"):
        invalid.embed_documents(("one",))
    query = EmbeddingConfig(
        encode_documents, lambda text: repeat(1), SPEC, identity="query-infinite"
    )
    with pytest.raises(VectorValidationError, match="dimensions"):
        query.embed_query("q")


def test_provider_failure_is_not_reclassified():
    failure = RuntimeError("upstream temporarily unavailable")

    def unavailable(texts):
        raise failure

    configured = EmbeddingConfig(unavailable, encode_query, SPEC)
    with pytest.raises(RuntimeError) as caught:
        configured.embed_documents(("one",))
    assert caught.value is failure


def test_query_binding_and_chunker_revision_invalidate_real_artifacts(tmp_path):
    calls = []

    def counting(texts):
        calls.append(texts)
        return encode_documents(texts)

    runtime, _, _, _ = fixture(tmp_path)
    app = runtime.apps["sample"]
    configured = EmbeddingConfig(counting, encode_query, SPEC, identity="counted-pair")
    config = replace(app.retrieval, embedding=configured, chunker=ChunkingConfig())
    runtime = Runtime(runtime.database.path, [replace(app, retrieval=config)], activate=True)
    runtime.sync()
    assert len(calls) == 1
    runtime.indexing.reindex()
    runtime.drain()
    assert len(calls) == 1
    changed = EmbeddingConfig(counting, alternate_query, SPEC, identity="counted-pair")
    config = replace(config, embedding=changed)
    runtime = Runtime(runtime.database.path, [replace(app, retrieval=config)], activate=True)
    runtime.drain()
    assert len(calls) == 2
    config = replace(config, chunker=ChunkingConfig(revision="2"))
    runtime = Runtime(runtime.database.path, [replace(app, retrieval=config)], activate=True)
    runtime.drain()
    assert len(calls) == 3
    assert runtime.search("sample", "q", DEV)


def test_custom_chunk_iterable_is_bounded_by_existing_index_boundary(tmp_path):
    chunker = ChunkingConfig(lambda text: repeat(Chunk(text, 0, len(text))), identity="infinite")
    runtime, _, _, _ = fixture(tmp_path)
    app = runtime.apps["sample"]
    config = replace(app.retrieval, chunker=chunker, max_attempts=1)
    runtime = Runtime(runtime.database.path, [replace(app, retrieval=config)], activate=True)
    runtime.sync()
    with runtime.database.connection() as connection:
        build = connection.execute("SELECT state,error FROM semantic_builds").fetchone()
    assert build["state"] == "FAILED"
    assert "chunk limit" in build["error"]
