"""Retain Markdown content and describe headings without rendering HTML."""

from dataclasses import replace

from galmuri.contracts.documents import Document
from galmuri.contracts.files import File
from galmuri.parsing.structure import markdown_blocks
from galmuri.parsing.text import parse_text


def parse_markdown(file: File) -> tuple[Document, ...]:
    document = parse_text(file)[0]
    headings = [
        {"level": block.level, "text": block.title}
        for block in markdown_blocks(document.text)
        if block.level
    ]
    return (
        replace(
            document,
            metadata={**document.metadata, "format": "markdown", "headings": headings},
        ),
    )
