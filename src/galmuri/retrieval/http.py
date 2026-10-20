"""Bounded JSON requests to explicitly configured provider endpoints."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from galmuri.retrieval.errors import ProviderError

MAX_BODY = 32 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class ProviderHTTPError(ProviderError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"provider returned HTTP {status}")


def endpoint(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("provider URL must be HTTP(S) without credentials, query or fragment")
    return url.rstrip("/")


class JSONClient:
    def __init__(self, url: str, headers: dict[str, str], timeout: float):
        self.url = endpoint(url)
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.timeout = timeout
        if any(
            not isinstance(value, str)
            or not value
            or any(ord(character) < 32 or ord(character) > 126 for character in value)
            for value in headers.values()
        ):
            raise ValueError("provider credentials must be nonempty printable ASCII strings")
        self._headers = dict(headers)

    def request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        if data is not None and len(data) > MAX_BODY:
            raise ProviderError("provider request exceeds the byte limit")
        headers = {"Accept": "application/json", **self._headers}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BODY + 1)
        except HTTPError as exc:
            exc.close()
            raise ProviderHTTPError(exc.code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError("provider connection failed") from exc
        if len(raw) > MAX_BODY:
            raise ProviderError("provider response exceeds the byte limit")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ProviderError("provider returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ProviderError("provider response must be a JSON object")
        return result
