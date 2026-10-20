"""Permission collections have explicit shape; strings are never collections of grants."""

from collections.abc import Iterable, Mapping


def normalize_grants(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise TypeError("Permissions must be a collection of grant strings")
    grants = tuple(values)
    if not all(isinstance(value, str) and value for value in grants):
        raise TypeError("Permission grants must be nonempty strings")
    return tuple(dict.fromkeys(grants))


def valid_grants(values) -> bool:
    """Fail closed for malformed stored values, including older custom-handler output."""
    return isinstance(values, (tuple, list)) and all(
        isinstance(value, str) and bool(value) for value in values
    )
