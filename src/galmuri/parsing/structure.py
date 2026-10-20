"""Exact spans for common top-level Markdown blocks, without rendering text.

This is a conservative boundary scanner, not a CommonMark renderer. It recognizes
paragraphs, ATX/setext headings and backtick/tilde fences. Container syntax (lists,
quotes, HTML and tables) stays ordinary text; no content is stripped or rewritten.
"""

import re
from dataclasses import dataclass

_LINES = re.compile(r"[^\r\n]+(?:\r\n|\r|\n)?|(?:\r\n|\r|\n)")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_CONTAINER = re.compile(r"^(?: {4}|\t| {0,3}(?:>|[-+*][ \t]|[0-9]{1,9}[.)][ \t]))")


@dataclass(frozen=True)
class TextBlock:
    start: int
    end: int
    level: int = 0
    title: str = ""


def _heading(line):
    match = _ATX.fullmatch(line)
    if match is None:
        return None
    title = (match[2] or "").strip(" \t")
    # Closing hashes require preceding whitespace; a literal "C#" stays intact.
    title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", title)
    return len(match[1]), title


def _fence(line):
    match = _FENCE.fullmatch(line)
    if match is None or (match[1][0] == "`" and "`" in match[2]):
        return None
    return match[1]


def _closes(line, marker):
    match = _FENCE.fullmatch(line)
    return (
        match is not None
        and match[1][0] == marker[0]
        and len(match[1]) >= len(marker)
        and not match[2].strip(" \t")
    )


def markdown_blocks(text: str) -> tuple[TextBlock, ...]:
    """Return contiguous spans covering every Unicode code point exactly once."""
    lines = tuple(_LINES.finditer(text))
    result = []
    index = 0
    while index < len(lines):
        start = index
        line = lines[index][0].rstrip("\r\n")
        heading = _heading(line)
        marker = _fence(line)
        if not line.strip(" \t"):
            index += 1
            while index < len(lines) and not lines[index][0].strip(" \t\r\n"):
                index += 1
        elif marker is not None:
            index += 1
            while index < len(lines):
                closing = _closes(lines[index][0].rstrip("\r\n"), marker)
                index += 1
                if closing:
                    break
        elif heading is not None:
            index += 1
        else:
            titles = [line]
            setext_allowed = not _CONTAINER.match(line) and not _SETEXT.fullmatch(line)
            index += 1
            while index < len(lines):
                following = lines[index][0].rstrip("\r\n")
                if not following.strip(" \t") or _heading(following) or _fence(following):
                    break
                underline = _SETEXT.fullmatch(following)
                if underline and setext_allowed:
                    heading = (
                        1 if underline[1][0] == "=" else 2,
                        "\n".join(title.strip(" \t") for title in titles),
                    )
                    index += 1
                    break
                titles.append(following)
                setext_allowed = setext_allowed and not _CONTAINER.match(following)
                index += 1
        level, title = heading or (0, "")
        result.append(TextBlock(lines[start].start(), lines[index - 1].end(), level, title))
    return tuple(result)
