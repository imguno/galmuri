"""Actual HTTP requests exercise session, account and token trust boundaries."""

import http.client
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from galmuri.exposure.auth.accounts import AccountAuthenticator
from galmuri.exposure.http import HttpAdapter
from galmuri.exposure.service import Service
from galmuri.identity import AuthenticationError, IdentityStore

PASSWORD = "long safe test password 42"


@pytest.fixture
def workspace(tmp_path):
    store = IdentityStore(tmp_path / "identity.db")
    admin = store.create_user("operator", PASSWORD, administrator=True)
    reader = store.create_user("reader", PASSWORD)
    service = Service(SimpleNamespace(apps={}))
    service.identity = store
    adapter = HttpAdapter(service, port=0, allow_insecure_loopback=True)
    with adapter.server() as server:
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, payload=None, *, cookie=None, csrf=None, token=None, origin=True):
            headers = {}
            if cookie:
                headers["Cookie"] = cookie
            if csrf:
                headers["X-CSRF-Token"] = csrf
            if token:
                headers["Authorization"] = "Bearer " + token
            if payload is not None:
                headers["Content-Type"] = "application/json"
                if origin:
                    headers["Origin"] = base if origin is True else origin
            req = Request(
                base + path,
                headers=headers,
                data=json.dumps(payload).encode() if payload is not None else None,
            )
            try:
                response = urlopen(req, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                content = response.read()
                value = (
                    json.loads(content)
                    if "application/json" in response.headers.get("Content-Type", "")
                    else content.decode()
                )
                return SimpleNamespace(status=response.status, headers=response.headers, data=value)

        def login(name="operator"):
            response = request("/auth/login", {"username": name, "password": PASSWORD})
            assert response.status == 200
            return response.headers["Set-Cookie"].split(";", 1)[0], response.data["result"]["csrf"]

        yield SimpleNamespace(
            store=store,
            admin=admin,
            reader=reader,
            request=request,
            login=login,
            server=server,
            base=base,
        )


def command(operation, **params):
    return {"operation": operation, "params": params}


def test_dashboard_public_shell_and_login_cookie_without_secret_response(workspace):
    w = workspace
    response = w.request("/dashboard")
    assert response.status == 200
    assert "Document workspace" in response.data
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert w.request("/dashboard/assets/app.js").status == 200
    assert w.request("/admin").status == 200
    assert not w.request("/auth/me").data["result"]["authenticated"]
    response = w.request("/auth/login", {"username": "operator", "password": PASSWORD})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert "token" not in response.data["result"]
    secret = cookie.split(";", 1)[0].split("=", 1)[1]
    assert secret not in json.dumps(response.data)
    me = w.request("/auth/me", cookie=cookie.split(";", 1)[0]).data["result"]
    assert me["user_id"] == w.admin["id"] and me["administrator"]


def test_login_and_cookie_mutations_require_origin_and_csrf(workspace):
    w = workspace
    assert (
        w.request(
            "/auth/login", {"username": "operator", "password": PASSWORD}, origin=False
        ).status
        == 403
    )
    assert (
        w.request(
            "/auth/login",
            {"username": "operator", "password": PASSWORD},
            origin="https://evil.example",
        ).status
        == 403
    )
    cookie, csrf = w.login()
    payload = command("groups.create", name="Developers")
    assert w.request("/dashboard/api", payload, cookie=cookie).status == 403
    assert (
        w.request("/dashboard/api", payload, cookie=cookie, csrf=csrf, origin=False).status == 403
    )
    response = w.request("/dashboard/api", payload, cookie=cookie, csrf=csrf)
    assert response.status == 200
    assert response.data["result"]["name"] == "Developers"
    logout = w.request("/auth/logout", {}, cookie=cookie, csrf=csrf)
    assert logout.status == 200 and "Max-Age=0" in logout.headers["Set-Cookie"]
    assert w.request("/auth/me", cookie=cookie).status == 401
    # An expired/revoked browser cookie must not prevent a fresh password login.
    assert w.request("/dashboard", cookie=cookie).status == 200
    assert (
        w.request(
            "/auth/login", {"username": "operator", "password": PASSWORD}, cookie=cookie
        ).status
        == 200
    )


def test_account_group_management_and_no_asserted_admin(workspace):
    w = workspace
    cookie, csrf = w.login()

    def call(operation, **params):
        return w.request("/dashboard/api", command(operation, **params), cookie=cookie, csrf=csrf)

    created = call("users.create", username="new-user", password=PASSWORD).data["result"]
    group = call("groups.create", name="Writers").data["result"]
    assert call("groups.add", group_id=group["id"], user_id=created["id"]).status == 200
    assert call("groups.members", group_id=group["id"]).data["result"][0]["id"] == created["id"]
    assert call("groups.remove", group_id=group["id"], user_id=created["id"]).status == 200
    assert call("users.enabled", user_id=created["id"], enabled=False).status == 200
    assert (
        call("users.create", username="x", password=PASSWORD, subject=w.admin["id"]).status == 400
    )
    reader_cookie, reader_csrf = w.login("reader")
    assert (
        w.request(
            "/dashboard/api", command("users.list"), cookie=reader_cookie, csrf=reader_csrf
        ).status
        == 403
    )
    assert w.request("/dashboard/api", command("users.list")).status == 401


def test_only_root_session_can_delegate_or_disable_root_accounts(workspace):
    w = workspace
    root = w.store.create_user("root-operator", PASSWORD, root=True)
    admin_cookie, admin_csrf = w.login()
    payload = command("users.create", username="delegated-root", password=PASSWORD, root=True)
    assert w.request("/dashboard/api", payload, cookie=admin_cookie, csrf=admin_csrf).status == 403
    assert (
        w.request(
            "/dashboard/api",
            command("users.enabled", user_id=root["id"], enabled=False),
            cookie=admin_cookie,
            csrf=admin_csrf,
        ).status
        == 403
    )
    root_cookie, root_csrf = w.login("root-operator")
    assert w.request("/auth/me", cookie=root_cookie).data["result"]["root"]
    delegated = w.request("/dashboard/api", payload, cookie=root_cookie, csrf=root_csrf)
    assert delegated.status == 200 and delegated.data["result"]["root"]
    assert delegated.data["result"]["administrator"]
    root_token = w.store.issue_token(root["id"], "Root MCP", scopes=["manage"])
    assert (
        w.request(
            "/dashboard/api",
            command("users.create", username="token-root", password=PASSWORD, root=True),
            token=root_token["token"],
        ).status
        == 403
    )


def test_token_self_service_ownership_attenuation_and_live_revocation(workspace):
    w = workspace
    cookie, csrf = w.login("reader")
    issued = w.request(
        "/dashboard/api",
        command("tokens.create", name="Assistant", scopes=["read"], apps=["readonly"], ttl=3600),
        cookie=cookie,
        csrf=csrf,
    )
    assert issued.status == 200
    credential = issued.data["result"]
    listing = w.request("/dashboard/api", command("tokens.list"), cookie=cookie, csrf=csrf)
    assert credential["token"] not in json.dumps(listing.data)
    auth = AccountAuthenticator(w.store)
    assert auth.authenticate("Bearer " + credential["token"]).subject == w.reader["id"]
    assert (
        w.request(
            "/dashboard/api",
            command("tokens.create", name="Escalation", scopes=["manage"]),
            token=credential["token"],
        ).status
        == 403
    )
    admin_token = w.store.issue_token(
        w.admin["id"], "Limited admin", scopes=["manage"], apps=["readonly"]
    )
    assert (
        w.request("/dashboard/api", command("users.list"), token=admin_token["token"]).status == 403
    )
    assert (
        w.request(
            "/dashboard/api",
            command(
                "users.create", username="escalated-admin", password=PASSWORD, administrator=True
            ),
            token=admin_token["token"],
        ).status
        == 403
    )
    assert not any(user["username"] == "escalated-admin" for user in w.store.list_users())
    admin_cookie, admin_csrf = w.login()
    assert w.request(
        "/dashboard/api",
        command("tokens.revoke", token_id=credential["id"]),
        cookie=admin_cookie,
        csrf=admin_csrf,
    ).status in {400, 404}
    assert (
        w.request(
            "/dashboard/api",
            command("tokens.revoke", token_id=credential["id"]),
            cookie=cookie,
            csrf=csrf,
        ).status
        == 200
    )
    assert w.request("/auth/me", token=credential["token"]).status == 401


def test_duplicate_headers_json_and_mixed_credentials_rejected(workspace):
    w = workspace
    cookie, csrf = w.login()
    credential = w.store.issue_token(w.admin["id"], "API")
    assert w.request("/auth/me", cookie=cookie, token=credential["token"]).status == 400
    assert w.request("/auth/me", cookie=cookie + "; " + cookie).status == 400
    connection = http.client.HTTPConnection("127.0.0.1", w.server.server_port, timeout=5)
    connection.putrequest("GET", "/auth/me")
    connection.putheader("Authorization", "Bearer " + credential["token"])
    connection.putheader("Authorization", "Bearer attacker")
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    connection.close()
    body = b'{"username":"reader","username":"operator","password":"long safe test password 42"}'
    connection = http.client.HTTPConnection("127.0.0.1", w.server.server_port, timeout=5)
    connection.request(
        "POST",
        "/auth/login",
        body=body,
        headers={"Content-Type": "application/json", "Origin": w.base},
    )
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    connection.close()


def test_https_configuration_and_explicit_local_development(tmp_path):
    service = Service(SimpleNamespace(apps={}))
    service.identity = IdentityStore(tmp_path / "id.db")
    with pytest.raises(ValueError):
        HttpAdapter(service, host="0.0.0.0", allow_insecure_loopback=True)
    with pytest.raises(ValueError):
        HttpAdapter(service)
    with pytest.raises(ValueError):
        HttpAdapter(service, public_origin="https://example.org/path")
    adapter = HttpAdapter(service, host="0.0.0.0", public_origin="https://docs.example.org")
    assert "Secure" in adapter.sessions.cookie("secret")
    assert adapter.sessions.cookie_name.startswith("__Host-")
    from galmuri.exposure.auth import TokenAuthenticator

    with pytest.raises(ValueError):
        HttpAdapter(service, authenticator=TokenAuthenticator(), allow_insecure_loopback=True)
    with pytest.raises(ValueError):
        HttpAdapter(
            service,
            authenticator=AccountAuthenticator(IdentityStore(tmp_path / "other.db")),
            allow_insecure_loopback=True,
        )


def test_authenticator_invalid_credentials_never_fall_back_to_anonymous(workspace):
    auth = AccountAuthenticator(workspace.store, allow_anonymous=True)
    assert auth.authenticate(None).subject == "anonymous"
    from galmuri.exposure.service.errors import ExposureError

    with pytest.raises(ExposureError):
        auth.authenticate("Bearer invalid")
    with pytest.raises(ExposureError):
        auth.authenticate("Basic dXNlcjpwYXNz")
    with pytest.raises(AuthenticationError):
        workspace.store.authenticate("invalid")
