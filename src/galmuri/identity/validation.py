"""Validation never interpolates supplied secrets into errors."""

import unicodedata

from .errors import IdentityError


def name(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise IdentityError("Name must be text")
    display = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(display) <= 150 or any(unicodedata.category(c)[0] == "C" for c in display):
        raise IdentityError("Name must contain 1 to 150 printable characters")
    return display, display.casefold()


def password(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 15 <= len(value) <= 1024
        or any(unicodedata.category(c) == "Cs" for c in value)
    ):
        raise IdentityError("Password must contain 15 to 1024 characters")
    return value


def ttl(value: int, *, maximum: int = 365 * 86400) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise IdentityError("Credential lifetime is outside the supported range")
    return value


def restrictions(scopes, apps) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if isinstance(scopes, str) or isinstance(apps, str):
        raise IdentityError("Scopes and apps must be sequences")
    try:
        scopes, apps = tuple(scopes), tuple(apps)
    except TypeError:
        raise IdentityError("Scopes and apps must be sequences") from None
    if (
        not scopes
        or len(scopes) > 3
        or any(not isinstance(s, str) or s not in {"read", "write", "manage"} for s in scopes)
    ):
        raise IdentityError("Unsupported credential scope")
    if (
        not apps
        or len(apps) > 256
        or any(
            not isinstance(a, str)
            or not 1 <= len(a) <= 150
            or any(unicodedata.category(c)[0] == "C" for c in a)
            for a in apps
        )
    ):
        raise IdentityError("Invalid app allow-list")
    if "*" in apps and apps != ("*",):
        raise IdentityError("Wildcard app access must stand alone")
    return tuple(sorted(set(scopes))), tuple(sorted(set(apps)))
