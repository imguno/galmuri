"""Source access implementations; user authorization belongs to ingestion."""

from galmuri.sources.local import LocalFiles, ReadOnlyFiles

__all__ = ["LocalFiles", "ReadOnlyFiles"]
