"""Tokenizer-independent chunk contracts, separate from FastEmbed integration tests."""

from itertools import islice

import pytest

from galmuri.retrieval import CharacterChunker, Chunk, TokenBudgetChunker


def bounded(counter=len, limit=3, *, base=None, identity="test-counter:v1"):
    return TokenBudgetChunker(base or CharacterChunker(100, 0), counter, limit, identity=identity)


def test_every_character_and_exact_offsets_survive_subdivision():
    text = "첫 문단\n\n두 번째 문단🙂끝"
    chunks = tuple(bounded().split(text))
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(chunk.text == text[chunk.start : chunk.end] for chunk in chunks)
    assert all(len(chunk.text) <= 3 for chunk in chunks)


def test_nonmonotonic_counter_does_not_discard_valid_longer_spans():
    def counter(text):
        return 1 if len(text) == 3 else 10

    chunks = tuple(bounded(counter, 2).split("abcdef"))
    assert [chunk.text for chunk in chunks] == ["abc", "def"]
    assert all(counter(chunk.text) <= 2 for chunk in chunks)


@pytest.mark.parametrize("count", [True, -1, 1.5, "2", None])
def test_invalid_counter_result_fails_explicitly(count):
    with pytest.raises(ValueError, match="nonnegative integer"):
        tuple(bounded(lambda text: count).split("text"))


def test_impossible_single_code_point_has_an_explicit_failure():
    with pytest.raises(ValueError, match="single Unicode code point"):
        tuple(bounded(lambda text: 100).split("🙂"))


def test_bad_base_anchors_are_rejected():
    class Wrong:
        identity = "wrong"

        def split(self, text):
            return (Chunk("other", 0, 5),)

    with pytest.raises(ValueError, match="anchors"):
        tuple(bounded(base=Wrong()).split("input"))


def test_unbounded_base_is_consumed_lazily():
    seen = []

    class Infinite:
        identity = "infinite"

        def split(self, text):
            while True:
                seen.append(1)
                yield Chunk(text, 0, len(text))

    chunks = tuple(islice(bounded(base=Infinite()).split("abc"), 2))
    assert len(chunks) == len(seen) == 2


def test_counter_is_not_invoked_during_configuration_or_for_empty_input():
    def unexpected(text):
        pytest.fail("No text was submitted to the tokenizer")

    chunker = bounded(unexpected)
    assert tuple(chunker.split("")) == ()


def test_tokenizer_revision_and_budget_are_part_of_compatibility():
    original = bounded()
    assert original.identity == bounded().identity
    assert original.identity != bounded(identity="test-counter:v2").identity
    assert original.identity != bounded(limit=2).identity


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_budget_is_rejected(limit):
    with pytest.raises(ValueError):
        bounded(limit=limit)
