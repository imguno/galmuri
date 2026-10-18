"""Retain Markdown content and describe headings without rendering HTML."""

import re
from dataclasses import replace

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File
from galmuri.parsing.text import parse_text


def parse_markdown(file: File) -> tuple[Document, ...]:
    document = parse_text(file)[0]
    headings = []
    fence = None
    for line in document.text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None and (match := re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)):
            headings.append({"level": len(match[1]), "text": match[2]})
    return (
        replace(
            document,
            metadata={**document.metadata, "format": "markdown", "headings": headings},
        ),
    )
