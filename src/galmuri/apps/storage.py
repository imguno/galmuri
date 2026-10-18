"""App-owned persistence selection; connection details belong to settings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConfig:
    alias: str = "default"
    namespace: str | None = None

    def __post_init__(self):
        if not isinstance(self.alias, str) or not self.alias or len(self.alias) > 100:
            raise ValueError("Database alias must name a configured database")
        if self.namespace is not None and (
            not isinstance(self.namespace, str) or not self.namespace or len(self.namespace) > 63
        ):
            raise ValueError(
                "Database namespace must be a nonempty string of at most 63 characters"
            )
