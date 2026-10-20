"""Document boundaries stay intact while chunk boundaries follow useful structure."""

import pytest

from galmuri import File, FileRef
from galmuri.parsing import parse_markdown
from galmuri.retrieval import CharacterChunker, ChunkingConfig, StructureChunker


def assert_coverage(text, chunks, size):
    covered = [False] * len(text)
    previous_start = -1
    for chunk in chunks:
        assert previous_start < chunk.start
        assert chunk.text == text[chunk.start : chunk.end]
        assert 0 < len(chunk.text) <= size
        covered[chunk.start : chunk.end] = [True] * len(chunk.text)
        previous_start = chunk.start
    assert all(covered)


def test_sections_are_distinct_even_when_whole_document_fits():
    text = "# 설치\n설치 방법입니다.\n\n## 실행\n실행 방법입니다.\n"
    chunks = StructureChunker().split(text)
    assert [chunk.text for chunk in chunks] == [
        "# 설치\n설치 방법입니다.\n\n",
        "## 실행\n실행 방법입니다.\n",
    ]
    assert_coverage(text, chunks, 800)
    assert ChunkingConfig().split(text) == chunks
    assert len(CharacterChunker().split(text)) == 1


def test_plain_paragraphs_pack_without_breaking_fitting_blocks():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = StructureChunker(size=38, overlap=4).split(text)
    assert len(chunks) == 2
    assert chunks[0].text == "First paragraph.\n\nSecond paragraph.\n\n"
    assert chunks[1].text == "Third paragraph."
    assert_coverage(text, chunks, 38)


def test_short_fenced_block_stays_whole_and_ignores_internal_headings():
    fence = "````python\n# not a heading\n```\n## still code\n````\n"
    text = "# Title\n" + fence + "\n## Next\nok"
    chunks = StructureChunker(size=len(fence), overlap=5).split(text)
    assert any(chunk.text == fence for chunk in chunks)
    assert_coverage(text, chunks, len(fence))
    document = parse_markdown(File(FileRef("guide.md", "v1"), text.encode()))[0]
    assert document.metadata["headings"] == [
        {"level": 1, "text": "Title"},
        {"level": 2, "text": "Next"},
    ]


@pytest.mark.parametrize(
    "fence",
    [
        "~~~lang\n# hidden\n~~~~\n",
        "```lang\n# hidden\n``` trailing text\n## hidden too\n```\n",
        "```lang\n# hidden\n",
    ],
)
def test_tilde_trailing_text_and_unclosed_fences(fence):
    text = "# Visible\n" + fence
    document = parse_markdown(File(FileRef("guide.md", "1"), text.encode()))[0]
    assert document.metadata["headings"] == [{"level": 1, "text": "Visible"}]
    assert len(StructureChunker().split(text)) == 1


def test_setext_unicode_crlf_and_literal_hash_titles_preserve_document_identity():
    text = "설치😀\r\n======\r\n설치 방법\r\n\r\n# C#\r\n코드\r\n\r\n끝\r\n---\r\n"
    file = File(FileRef("stable-id", "revision", {"name": "guide.md"}), text.encode())
    documents = parse_markdown(file)
    assert len(documents) == 1
    assert documents[0].key == "stable-id"
    assert documents[0].text == text
    assert documents[0].metadata["headings"] == [
        {"level": 1, "text": "설치😀"},
        {"level": 1, "text": "C#"},
        {"level": 2, "text": "끝"},
    ]
    chunks = StructureChunker().split(text)
    assert len(chunks) == 3
    assert_coverage(text, chunks, 800)


def test_oversized_block_overlaps_inside_its_own_section_only():
    text = "# First\n" + "가나다😀" * 15 + "\n\n# Second\n" + "abc" * 30
    chunks = StructureChunker(size=23, overlap=6).split(text)
    boundary = text.index("# Second")
    assert all(not (chunk.start < boundary < chunk.end) for chunk in chunks)
    overlapping = [
        left.end - right.start
        for left, right in zip(chunks, chunks[1:], strict=False)
        if left.end > right.start
    ]
    assert overlapping and set(overlapping) == {6}
    assert_coverage(text, chunks, 23)


@pytest.mark.parametrize("text", ["", "a", "\n \t\r\n", "한😀e\u0301" * 12, "```py\n" + "x" * 90])
@pytest.mark.parametrize("size,overlap", [(1, 0), (7, 3), (800, 80)])
def test_boundaries_cover_empty_whitespace_and_long_unicode_blocks(text, size, overlap):
    chunks = StructureChunker(size, overlap).split(text)
    assert_coverage(text, chunks, size)
    assert chunks == StructureChunker(size, overlap).split(text)
    if not text:
        assert chunks == ()


def test_indented_or_escaped_hashes_and_number_signs_are_not_sections():
    text = "    # code\n\n\\# escaped\n\n#hashtag\n\n####### too many\n"
    document = parse_markdown(File(FileRef("id", "1"), text.encode()))[0]
    assert document.metadata["headings"] == []
    assert len(StructureChunker().split(text)) == 1


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1), (True, 0), (5, True)])
def test_invalid_size_or_overlap(size, overlap):
    with pytest.raises(ValueError):
        StructureChunker(size, overlap)


def test_identity_covers_policy_and_differs_from_fixed_character_windows():
    chunker = StructureChunker()
    assert chunker.identity == StructureChunker().identity
    assert chunker.identity != CharacterChunker().identity
    assert chunker.identity != StructureChunker(size=900).identity
    assert chunker.identity != StructureChunker(overlap=0).identity
