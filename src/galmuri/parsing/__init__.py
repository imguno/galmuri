"""File-to-document parsers; source access and publication live in ingestion."""

from galmuri.parsing.configuration import ParsingConfig
from galmuri.parsing.markdown import parse_markdown
from galmuri.parsing.python import parse_python
from galmuri.parsing.text import parse_text


def parse_auto(file):
    """Select a built-in format parser without importing input source code."""
    if file.ref.suffix in {".md", ".markdown"}:
        return parse_markdown(file)
    if file.ref.suffix == ".py":
        return parse_python(file)
    return parse_text(file)


__all__ = ["ParsingConfig", "parse_auto", "parse_markdown", "parse_python", "parse_text"]
