"""Credentials become verified principals only through the identity backend."""

from galmuri.contracts.documents import Principal
from galmuri.exposure.service.errors import ExposureError
from galmuri.identity import AuthenticationError


class AccountAuthenticator:
    def __init__(self, store, *, allow_anonymous=False):
        self.store = store
        self.allow_anonymous = allow_anonymous

    def authenticate(self, authorization):
        if authorization is None and self.allow_anonymous:
            return Principal()
        if not isinstance(authorization, str):
            raise ExposureError("unauthenticated", "Valid credentials are required")
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or " " in token:
            raise ExposureError("unauthenticated", "Valid credentials are required")
        try:
            return self.store.authenticate(token)
        except AuthenticationError:
            raise ExposureError("unauthenticated", "Valid credentials are required") from None
