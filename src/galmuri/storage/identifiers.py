"""Identifiers are configuration, never interpolated arbitrary SQL."""

import re


def identifier(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value) is None:
        raise ValueError("Database identifiers must contain ASCII letters, digits or underscores")
    return value
