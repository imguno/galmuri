"""Errors safe to expose at the authentication boundary."""


class AuthenticationError(ValueError):
    """A credential or login could not be verified."""


class IdentityError(ValueError):
    """A directory operation violates its public contract."""
