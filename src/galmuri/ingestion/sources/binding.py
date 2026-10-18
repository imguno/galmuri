"""Provider IO remains in resource-access; this boundary chooses an adapter."""

from duru import Provider

from galmuri.ingestion.sources.resources import Resources


def bind(source):
    if isinstance(source, Provider):
        root = getattr(source, "root_uri", None)
        if not isinstance(root, str) or not root:
            raise ValueError(
                "Provider has no root_uri; use Resources(provider, root_uri) explicitly"
            )
        return Resources(source, root)
    return source
