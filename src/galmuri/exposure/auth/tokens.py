"""Authentication is supplied by the host, never operation arguments."""

import base64
import hmac
from collections.abc import Mapping
from typing import Protocol

from galmuri.contracts.documents import Principal
from galmuri.exposure.service.errors import ExposureError


class Authenticator(Protocol):
    def authenticate(self, authorization: str | None) -> Principal: ...


class TokenAuthenticator:
    def __init__(self, tokens: Mapping[str, Principal] | None = None, *, allow_anonymous=False):
        self.tokens = dict(tokens or {})
        if any(not token for token in self.tokens):
            raise ValueError("Authentication tokens must be nonempty")
        self.allow_anonymous = allow_anonymous

    def authenticate(self, authorization: str | None) -> Principal:
        if authorization is None and self.allow_anonymous:
            return Principal()
        token = ""
        if authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() == "bearer":
                token = value
            elif scheme.lower() == "basic":
                try:
                    decoded = base64.b64decode(value, validate=True).decode("utf-8")
                    token = decoded.split(":", 1)[1]
                except (ValueError, UnicodeDecodeError, IndexError):
                    pass
        for expected, principal in self.tokens.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                return principal
        raise ExposureError("unauthenticated", "Valid host-configured credentials are required")
