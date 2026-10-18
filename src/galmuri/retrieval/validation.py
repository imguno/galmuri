"""Validation of untrusted vector provider inputs and outputs."""

import math
from itertools import islice
from numbers import Real
from uuid import UUID

from galmuri.retrieval.errors import VectorValidationError


def vector(values, dimensions: int) -> tuple[float, ...]:
    """Require a finite nonzero dense vector of exactly the configured width."""
    positive_int(dimensions, "dimensions")
    try:
        components = tuple(islice(iter(values), dimensions + 1))
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in components):
            raise VectorValidationError("vector must contain real numbers")
        result = tuple(float(value) for value in components)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VectorValidationError("vector must contain numbers") from exc
    if len(result) != dimensions:
        raise VectorValidationError("vector dimensions differ from the configured dimensions")
    if not all(math.isfinite(value) for value in result):
        raise VectorValidationError("vector must contain finite numbers")
    if not any(result):
        raise VectorValidationError("zero vectors have no cosine direction")
    return result


def point_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise VectorValidationError("vector point id must be a UUID") from exc


def positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def label(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
