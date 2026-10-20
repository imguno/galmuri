"""Bounded HTTP adapter with independent session and presentation boundaries."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.http.admin import render_admin
from galmuri.exposure.service.errors import ExposureError, failure

STATUS = {
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "unsupported": 405,
    "invalid_request": 400,
    "conflict": 409,
    "effect_unknown": 409,
    "internal_error": 500,
    "too_large": 413,
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


class HttpAdapter:
    def __init__(
        self,
        service,
        *,
        authenticator=None,
        host="127.0.0.1",
        port=8000,
        max_body_bytes=1048576,
        public_origin=None,
        allow_insecure_loopback=False,
        session_ttl=3600,
    ):
        self.service = service
        self.authenticator = authenticator or TokenAuthenticator()
        self.host, self.port = host, port
        self.max_body_bytes = max_body_bytes
        self.sessions = self.dashboard = None
        identity = getattr(service, "identity", None)
        if identity is not None:
            from galmuri.exposure.auth.accounts import AccountAuthenticator
            from galmuri.exposure.dashboard.routes import DashboardRoutes
            from galmuri.exposure.dashboard.session import Sessions

            if authenticator is not None and (
                not isinstance(authenticator, AccountAuthenticator)
                or authenticator.store is not identity
            ):
                raise ValueError("Identity HTTP requires its account authenticator")
            self.sessions = Sessions(
                identity,
                host=host,
                public_origin=public_origin,
                allow_insecure_loopback=allow_insecure_loopback,
                ttl=session_ttl,
            )
            self.dashboard = DashboardRoutes(service, self.sessions)
            if authenticator is None:
                self.authenticator = AccountAuthenticator(identity, allow_anonymous=True)

    def build_server(self):
        adapter = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def log_message(self, format, *args):
                pass

            def security_headers(self):
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                policy = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                )
                if not adapter.dashboard:
                    policy = (
                        "default-src 'self'; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
                    )
                self.send_header("Content-Security-Policy", policy)
                if adapter.sessions and adapter.sessions.secure:
                    self.send_header("Strict-Transport-Security", "max-age=31536000")

            def respond(self, response, status=None, headers=None):
                status = status or (
                    200 if response["ok"] else STATUS.get(response["error"]["code"], 500)
                )
                data = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.security_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                if (
                    status == 401
                    and not adapter.dashboard
                    and urlsplit(self.path).path.rstrip("/") == "/admin"
                ):
                    self.send_header("WWW-Authenticate", 'Basic realm="Source administration"')
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def validate_headers(self):
                protected = (
                    "Authorization",
                    "Cookie",
                    "Content-Length",
                    "Content-Type",
                    "Host",
                    "Origin",
                    "X-CSRF-Token",
                )
                for header in protected:
                    if len(self.headers.get_all(header, [])) > 1:
                        raise ExposureError("invalid_request", "Duplicate request headers")

            def context(self):
                self.validate_headers()
                if adapter.sessions:
                    return adapter.sessions.context(self, adapter.authenticator)
                return adapter.authenticator.authenticate(self.headers.get("Authorization")), None

            def do_GET(self):
                try:
                    path = urlsplit(self.path)
                    if adapter.dashboard and (
                        path.path.rstrip("/") in {"/dashboard", "/admin"}
                        or path.path.startswith("/dashboard/assets/")
                    ):
                        self.validate_headers()
                        adapter.sessions.expected_origin(self)
                        if adapter.dashboard.get(self, None, None):
                            return
                    principal, raw = self.context()
                    if adapter.dashboard and adapter.dashboard.get(self, principal, raw):
                        return
                    if not adapter.dashboard and path.path in {"/admin", "/admin/"}:
                        status = adapter.service.call("status", {}, principal)
                        if not status["ok"]:
                            self.respond(status)
                            return
                        data = render_admin(
                            adapter.service.capabilities(), status["result"]
                        ).encode()
                        self.send_response(200)
                        self.security_headers()
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    if path.path.startswith("/api/"):
                        operation = path.path.removeprefix("/api/")
                        if operation not in {
                            "capabilities",
                            "describe",
                            "read",
                            "search",
                            "status",
                            "documents",
                            "permission_inventory",
                        }:
                            raise ExposureError("unsupported", "Use POST /api/call for commands")
                        query = parse_qs(path.query, keep_blank_values=True, max_num_fields=32)
                        if any(len(values) != 1 for values in query.values()):
                            raise ExposureError("invalid_request", "Duplicate parameters")
                        params = {key: values[0] for key, values in query.items()}
                        for key in ("limit", "offset"):
                            if key in params:
                                try:
                                    params[key] = int(params[key])
                                except ValueError:
                                    raise ExposureError(
                                        "invalid_request", f"Invalid {key}"
                                    ) from None
                        self.respond(adapter.service.call(operation, params, principal))
                        return
                    raise ExposureError("not_found", "Unknown endpoint")
                except ExposureError as exc:
                    self.respond(failure(exc.code, str(exc)))
                except (ValueError, UnicodeError):
                    self.respond(failure("invalid_request", "Invalid request"))

            def body(self):
                if self.headers.get_content_type() != "application/json":
                    raise ExposureError("invalid_request", "Use application/json")
                if self.headers.get("Transfer-Encoding"):
                    raise ExposureError("invalid_request", "Transfer encoding is not supported")
                try:
                    size = int(self.headers.get("Content-Length", "-1"))
                except ValueError:
                    raise ExposureError("invalid_request", "Invalid content length") from None
                if size < 0:
                    raise ExposureError("invalid_request", "Content length is required")
                if size > adapter.max_body_bytes:
                    self.close_connection = True
                    raise ExposureError("too_large", "Request body exceeds the configured limit")
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ExposureError("invalid_request", "Incomplete request body")
                try:
                    payload = json.loads(data, object_pairs_hook=unique_object)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    raise ExposureError("invalid_request", "Invalid JSON body") from None
                if not isinstance(payload, dict):
                    raise ExposureError("invalid_request", "Body must be an object")
                return payload

            def do_POST(self):
                try:
                    if adapter.sessions and urlsplit(self.path).path == "/auth/login":
                        from galmuri.contracts.documents import Principal

                        self.validate_headers()
                        adapter.sessions.expected_origin(self)
                        principal, raw = Principal(), None
                    else:
                        principal, raw = self.context()
                    payload = self.body()
                    if adapter.dashboard and adapter.dashboard.post(self, payload, principal, raw):
                        return
                    if urlsplit(self.path).path != "/api/call":
                        raise ExposureError("not_found", "Unknown endpoint")
                    if adapter.sessions:
                        adapter.sessions.mutation(self, raw)
                    else:
                        origin = self.headers.get("Origin")
                        if origin and origin != "http://" + self.headers.get("Host", ""):
                            raise ExposureError(
                                "forbidden", "Cross-origin commands are not permitted"
                            )
                    if payload.keys() - {"operation", "params"}:
                        raise ExposureError("invalid_request", "Invalid command envelope")
                    response = adapter.service.call(
                        payload.get("operation"), payload.get("params", {}), principal
                    )
                    self.respond(response)
                except ExposureError as exc:
                    self.respond(failure(exc.code, str(exc)))
                except PermissionError:
                    self.respond(failure("forbidden", "This operation is not permitted"))

        return ThreadingHTTPServer((self.host, self.port), Handler)

    @contextmanager
    def server(self):
        server = self.build_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def serve_forever(self):
        with self.build_server() as server:
            server.serve_forever()

    def run(self):
        self.serve_forever()
