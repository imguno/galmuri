"""Failures at embedding and vector storage boundaries."""


class RetrievalError(RuntimeError):
    """A configured retrieval operation could not be completed."""


class ProviderError(RetrievalError):
    """An external provider failed or returned an invalid response."""


class VectorValidationError(ValueError):
    """A vector does not meet the embedding contract."""
