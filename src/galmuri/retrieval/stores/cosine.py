"""Stable normalization shared by exact cosine reference stores."""

import math


def unit(values: tuple[float, ...]) -> tuple[float, ...]:
    # Scaling first avoids overflow/underflow for valid large/small components.
    scale = max(abs(value) for value in values)
    scaled = tuple(value / scale for value in values)
    norm = math.hypot(*scaled)
    return tuple(value / norm for value in scaled)
