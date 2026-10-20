"""Public provider contracts and Unicode chunk boundaries."""

from dataclasses import replace
from itertools import repeat
from uuid import uuid4

import pytest

from galmuri.retrieval import (
    CharacterChunker,
    Chunk,
    EmbeddingProvider,
    EmbeddingSpec,
    RetrievalConfig,
    SQLiteVectorStore,
    VectorPoint,
    VectorValidationError,
)
from galmuri.retrieval.validation import vector


class Embeddings(EmbeddingProvider):
    @property
    def spec(self):
        return EmbeddingSpec("fixture", "two-dimensions", 2, "1")

    def embed_documents(self, texts):
        return tuple((1.0, 0.0) for _ in texts)

    def embed_query(self, text):
        return (1.0, 0.0)


def test_character_windows_are_bounded_unicode_anchors():
    text = "한글😀문서abcdefghi"
    chunker = CharacterChunker(5, 2)
    chunks = chunker.split(text)
    assert chunks[-1].end == len(text)
    assert all(text[item.start : item.end] == item.text for item in chunks)
    assert all(len(item.text) <= 5 for item in chunks)
    assert chunks[1].start == 3
    assert chunker.split("") == ()
    assert chunker.split("short") == (Chunk("short", 0, 5),)


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1), (True, 0)])
def test_character_invalid_windows(size, overlap):
    with pytest.raises(ValueError):
        CharacterChunker(size, overlap)


@pytest.mark.parametrize(
    "value", [(), (1,), (0, 0), (float("nan"), 1), (float("inf"), 1), ("1", 0), (True, 1), None]
)
def test_invalid_vectors(value):
    with pytest.raises(VectorValidationError):
        vector(value, 2)


def test_vector_validation_bounds_generator():
    with pytest.raises(VectorValidationError):
        vector(repeat(1.0), 2)


def test_configuration_identity_excludes_operational_policy(tmp_path):
    config = RetrievalConfig(Embeddings(), SQLiteVectorStore(tmp_path / "vectors.sqlite"))
    assert (
        replace(config, mode="hybrid", batch_size=2, retry_delay=0).fingerprint
        == config.fingerprint
    )
    assert replace(config, revision="2").fingerprint != config.fingerprint
    assert replace(config, chunker=CharacterChunker(10, 0)).fingerprint != config.fingerprint
    for change in (
        {"batch_size": 0},
        {"mode": "unknown"},
        {"lease_seconds": 0},
        {"retry_delay": float("nan")},
    ):
        with pytest.raises(ValueError):
            replace(config, **change)


def test_sqlite_exact_cosine_filter_before_limit_and_restart(tmp_path):
    path = tmp_path / "vectors.sqlite"
    store = SQLiteVectorStore(path)
    store.ensure("first", 2)
    private, public = str(uuid4()), str(uuid4())
    store.upsert("first", (VectorPoint(private, (1, 0)), VectorPoint(public, (1, 1))))
    matches = store.search("first", (1, 0), allowed_ids=(public,), limit=1)
    assert matches[0].id == public
    assert matches[0].score == pytest.approx(2**-0.5)
    assert store.search("first", (1, 0), allowed_ids=(), limit=1) == ()
    restarted = SQLiteVectorStore(path)
    assert restarted.search("first", (1, 0), allowed_ids=(public,), limit=1) == matches
    restarted.upsert("first", (VectorPoint(public, (0, 1)),))
    assert restarted.search("first", (1, 0), allowed_ids=(public,), limit=1)[0].score == 0
    restarted.delete("first", (public,))
    restarted.delete("first", (public,))
    assert restarted.search("first", (1, 0), allowed_ids=(public,), limit=1) == ()
    with pytest.raises(RuntimeError, match="dimensions"):
        restarted.ensure("first", 3)


def test_sqlite_large_and_small_finite_values(tmp_path):
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    store.ensure("space", 2)
    identifier = str(uuid4())
    store.upsert("space", (VectorPoint(identifier, (1e308, 1e308)),))
    result = store.search("space", (1e-308, 1e-308), allowed_ids=(identifier,), limit=1)
    assert result[0].score == pytest.approx(1)


def test_sqlite_namespace_and_batch_atomicity(tmp_path):
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    store.ensure("one", 2)
    store.ensure("two", 2)
    identifier = str(uuid4())
    with pytest.raises(VectorValidationError):
        store.upsert("one", (VectorPoint(identifier, (1, 0)), VectorPoint("bad", (1, 0))))
    assert store.search("one", (1, 0), allowed_ids=(identifier,), limit=1) == ()
    store.upsert("one", (VectorPoint(identifier, (1, 0)),))
    assert store.search("two", (1, 0), allowed_ids=(identifier,), limit=1) == ()


def test_sqlite_large_authorized_set(tmp_path):
    store = SQLiteVectorStore(tmp_path / "vectors.sqlite")
    store.ensure("space", 2)
    identifiers = tuple(str(uuid4()) for _ in range(1100))
    store.upsert("space", tuple(VectorPoint(value, (1, 0)) for value in identifiers))
    assert len(store.search("space", (1, 0), allowed_ids=identifiers, limit=1100)) == 1100
