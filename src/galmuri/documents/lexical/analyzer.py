"""Small deterministic analyzer shared by indexing and queries.

Hangul bigrams tolerate particles and spacing changes without pretending to be a
morphological analyzer. Search requires all word terms and at least half of the
distinct Hangul bigrams, so an unmatched particle need not eliminate a match.
"""

import hashlib
import re
import unicodedata
from collections import Counter

VERSION = "unicode-hangul-bigram-v2"
MAX_QUERY_CHARACTERS = 4096
MAX_QUERY_TERMS = 128
_PARTS = re.compile(r"[가-힣]+|[^\W가-힣]+", re.UNICODE)
_HANGUL_SPACING = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")


def _tokens(text, *, indexing):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = _HANGUL_SPACING.sub("", normalized)
    for part in _PARTS.findall(normalized):
        if "가" <= part[0] <= "힣":
            if indexing or len(part) == 1:
                yield from ("u:" + character for character in part)
            yield from ("h:" + part[i : i + 2] for i in range(len(part) - 1))
        elif part.strip("_"):
            # PostgreSQL B-tree entries have a finite size. Very long words
            # (minified source/base64, for example) still get exact identity
            # without making ingestion fail or storing unbounded index keys.
            yield (
                "w:" + part
                if len(part) <= 128
                else "w#:" + hashlib.sha256(part.encode("utf-8")).hexdigest()
            )


def analyze(text):
    """Prepare immutable-by-convention term frequencies before acceptance."""
    return Counter(_tokens(text, indexing=True))


def query_terms(text):
    if not isinstance(text, str):
        raise TypeError("query must be text")
    if len(text) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"query must contain at most {MAX_QUERY_CHARACTERS} characters")
    terms = tuple(dict.fromkeys(_tokens(text, indexing=False)))
    if len(terms) > MAX_QUERY_TERMS:
        raise ValueError(f"query must contain at most {MAX_QUERY_TERMS} analyzed terms")
    return terms
