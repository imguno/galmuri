"""Account HTTP routes; all document operations use the shared Service."""

from importlib.resources import files
from urllib.parse import urlsplit

from galmuri.exposure.dashboard.accounts import FIELDS, account_call
from galmuri.exposure.service.errors import ExposureError
from galmuri.identity import AuthenticationError


class DashboardRoutes:
    def __init__(self, service, sessions):
        self.service, self.sessions = service, sessions

    def get(self, handler, principal, raw):
        path = urlsplit(handler.path).path.rstrip("/")
        if path in {"/admin", "/dashboard"}:
            self.asset(handler, "index.html", "text/html; charset=utf-8")
            return True
        if path in {"/dashboard/assets/app.js", "/dashboard/assets/style.css"}:
            name = path.rsplit("/", 1)[1]
            kind = "text/javascript" if name.endswith(".js") else "text/css"
            self.asset(handler, name, kind)
            return True
        if path == "/auth/me":
            authenticated = getattr(principal, "is_authenticated", False)
            username = None
            if authenticated:
                username = next(
                    (
                        user["username"]
                        for user in self.sessions.store.list_users()
                        if user["id"] == principal.subject
                    ),
                    None,
                )
            handler.respond(
                {
                    "ok": True,
                    "result": {
                        "authenticated": authenticated,
                        "user_id": principal.subject if authenticated else None,
                        "username": username,
                        "administrator": bool(principal.administrator),
                        "root": bool(getattr(principal, "root", False)),
                        "csrf": self.sessions.csrf(raw) if raw else None,
                    },
                }
            )
            return True
        return False

    def post(self, handler, payload, principal, raw):
        path = urlsplit(handler.path).path
        if path == "/auth/login":
            self.sessions.mutation(handler, raw, login=True)
            if set(payload) != {"username", "password"}:
                raise ExposureError("invalid_request", "Username and password are required")
            if (
                not isinstance(payload["username"], str)
                or not 1 <= len(payload["username"]) <= 256
                or not isinstance(payload["password"], str)
                or not 15 <= len(payload["password"]) <= 1024
            ):
                raise ExposureError("unauthenticated", "Invalid username or password")
            try:
                credential = self.sessions.store.login(
                    payload["username"],
                    payload["password"],
                    ttl=self.sessions.ttl,
                    rate_key=handler.client_address[0],
                )
            except AuthenticationError:
                raise ExposureError("unauthenticated", "Invalid username or password") from None
            token = credential["token"]
            handler.respond(
                {"ok": True, "result": {"csrf": self.sessions.csrf(token)}},
                headers={"Set-Cookie": self.sessions.cookie(token)},
            )
            return True
        if path == "/auth/logout":
            self.sessions.mutation(handler, raw)
            if payload:
                raise ExposureError("invalid_request", "Logout takes no parameters")
            if raw:
                self.sessions.store.revoke_token(principal.credential_id, user_id=principal.subject)
            handler.respond(
                {"ok": True, "result": None}, headers={"Set-Cookie": self.sessions.cookie()}
            )
            return True
        if path == "/dashboard/api":
            self.sessions.mutation(handler, raw)
            if set(payload) != {"operation", "params"}:
                raise ExposureError("invalid_request", "Invalid command envelope")
            operation, params = payload["operation"], payload["params"]
            if not isinstance(operation, str):
                raise ExposureError("invalid_request", "Invalid operation")
            if operation in FIELDS:
                try:
                    result = account_call(self.sessions.store, principal, operation, params)
                except (ValueError, TypeError):
                    raise ExposureError("invalid_request", "Invalid account request") from None
                except KeyError:
                    raise ExposureError("not_found", "Account record was not found") from None
                headers = (
                    {"Set-Cookie": self.sessions.cookie()}
                    if operation == "password.change"
                    else None
                )
                handler.respond({"ok": True, "result": result}, headers=headers)
            else:
                handler.respond(self.service.call(operation, params, principal))
            return True
        return False

    @staticmethod
    def asset(handler, name, content_type):
        content = files("galmuri.exposure.dashboard.assets").joinpath(name).read_bytes()
        handler.send_response(200)
        handler.security_headers()
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)
