"""Normalize independent resource providers at the ingestion boundary."""

from galmuri.ingestion.sources.binding import bind
from galmuri.ingestion.sources.resources import ReadOnlyResources, Resources

__all__ = ["bind", "ReadOnlyResources", "Resources"]
