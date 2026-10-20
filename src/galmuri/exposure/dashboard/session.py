"""HTTP session binding, deployment origin and CSRF boundary."""

import hashlib
import hmac
import ipaddress
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from galmuri.exposure.service.errors import ExposureError
from galmuri.identity import AuthenticationError


def loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Sessions:
    def __init__(self, store, *, host, public_origin, allow_insecure_loopback, ttl):
        if type(ttl) is not int or not 60 <= ttl <= 86400:
            raise ValueError("Session TTL must be between 60 and 86400 seconds")
        self.store, self.ttl = store, ttl
        self.origin = public_origin
        if public_origin:
            url = urlsplit(public_origin)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("Public origin must be an HTTPS origin without a path")
            self.authority = url.netloc.lower()
            self.secure = True
        elif allow_insecure_loopback and loopback(host):
            self.authority = None
            self.secure = False
        else:
            raise ValueError("Identity HTTP requires HTTPS or explicit loopback development")
        self.cookie_name = "__Host-framework_session" if self.secure else "framework_session"

    def expected_origin(self, handler):
        host = handler.headers.get("Host", "")
        if self.authority:
            if host.lower() != self.authority:
                raise ExposureError("forbidden", "Unexpected request host")
            return self.origin
        parsed = urlsplit("http://" + host)
        try:
            valid = (
                loopback(parsed.hostname)
                and parsed.port == handler.server.server_port
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ExposureError("forbidden", "Unexpected request host")
        return "http://" + host

    def context(self, handler, authenticator):
        self.expected_origin(handler)
        authorization = handler.headers.get("Authorization")
        cookie = SimpleCookie()
        names = [
            item.partition("=")[0].strip() for item in handler.headers.get("Cookie", "").split(";")
        ]
        if names.count(self.cookie_name) > 1:
            raise ExposureError("invalid_request", "Duplicate session cookies")
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except Exception:
            raise ExposureError("unauthenticated", "Invalid session") from None
        value = cookie.get(self.cookie_name)
        raw = value.value if value else None
        if authorization and raw:
            raise ExposureError("invalid_request", "Use one credential mechanism")
        if raw:
            try:
                principal = self.store.authenticate(raw)
                if principal.credential_kind != "session":
                    raise AuthenticationError("Invalid session")
            except AuthenticationError:
                raise ExposureError("unauthenticated", "Valid session is required") from None
            return principal, raw
        return authenticator.authenticate(authorization), None

    @staticmethod
    def csrf(raw):
        return hashlib.sha256(("framework-csrf-v1:" + raw).encode()).hexdigest()

    def mutation(self, handler, raw, *, login=False):
        expected = self.expected_origin(handler)
        origin = handler.headers.get("Origin")
        if origin and origin != expected:
            raise ExposureError("forbidden", "Cross-origin commands are not permitted")
        if raw or login:
            if origin != expected:
                raise ExposureError("forbidden", "Same-origin request is required")
        if raw:
            token = handler.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(token.encode(), self.csrf(raw).encode()):
                raise ExposureError("forbidden", "Valid CSRF token is required")

    def cookie(self, raw=None):
        value = raw or ""
        age = self.ttl if raw else 0
        return f"{self.cookie_name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}" + (
            "; Secure" if self.secure else ""
        )
