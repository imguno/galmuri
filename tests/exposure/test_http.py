import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.http import HttpAdapter
from galmuri.exposure.service import Service

from .fakes import FakeRuntime


def test_http_actual_requests_admin_commands_and_authorization():
    runtime = FakeRuntime()
    auth = TokenAuthenticator(
        {
            "operator": Principal("ops", administrator=True),
            "reader": Principal("reader"),
        }
    )
    adapter = HttpAdapter(Service(runtime), authenticator=auth, port=0, max_body_bytes=1024)
    with adapter.server() as server:
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, token=None, payload=None, **extra):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            headers.update(extra)
            req = Request(
                base + path,
                headers=headers,
                data=json.dumps(payload).encode() if payload is not None else None,
            )
            try:
                return urlopen(req, timeout=5)
            except HTTPError as exc:
                return exc

        with request("/admin") as response:
            assert response.status == 401
            assert response.headers["WWW-Authenticate"].startswith("Basic")
        basic = base64.b64encode(b"developer:operator").decode()
        with request("/admin", Authorization=f"Basic {basic}") as response:
            page = response.read().decode()
            assert response.status == 200
            assert "Collect now" in page and "Document search" in page
            assert "operator" not in page
        with request("/admin", "reader") as response:
            assert response.status == 403
        with request(
            "/api/call", "operator", {"operation": "pause", "params": {"app": "readonly"}}
        ) as response:
            assert json.load(response)["result"]["state"] == "PAUSED"
        with request("/api/call", "reader", {"operation": "status", "params": {}}) as response:
            assert response.status == 403
        with request("/api/read?app=readonly&document_key=private", "operator") as response:
            assert response.status == 403  # Admin does not bypass document ACL.
        with request(
            "/api/call",
            "operator",
            {"operation": "sync", "params": {}},
            Origin="https://malicious.example",
        ) as response:
            assert response.status == 403
        with request(
            "/api/call", "operator", {"operation": "sync", "params": {}, "junk": "x" * 2048}
        ) as response:
            assert response.status == 413


def test_admin_escapes_app_metadata_and_runtime_output():
    from galmuri.exposure.http.admin import render_admin

    page = render_admin({'<script>alert("x")</script>': {}}, {"message": "<img src=x>"})
    assert '<script>alert("x")</script>' not in page
    assert "&lt;img src=x&gt;" in page
