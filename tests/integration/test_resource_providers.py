"""Exercise real library HTTP providers through framework discovery/publication."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from duru import GoogleDriveProvider, SlackProvider
from duru.providers.http import HttpTransport

from galmuri import App, Document, Principal
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto
from galmuri.runtime import Runtime
from galmuri.sources.resources import Resources


@pytest.fixture
def api():
    state = {"text": "connected knowledge", "version": "1", "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            state["requests"].append((parsed.path, self.headers.get("Authorization")))
            path = parsed.path
            if path == "/files":
                body = {"files": [{"id": "item"}], "incompleteSearch": False}
            elif path.startswith("/files/"):
                file_id = path.rsplit("/", 1)[-1]
                if query.get("alt") == ["media"]:
                    body = ("# Guide\n" + state["text"]).encode()
                else:
                    body = {
                        "id": file_id,
                        "name": "Independent name.md",
                        "version": state["version"],
                        "mimeType": (
                            "application/vnd.google-apps.folder"
                            if file_id == "folder"
                            else "text/markdown"
                        ),
                    }
            elif path == "/conversations.info":
                body = {"ok": True, "channel": {"id": "C1", "name": "Knowledge"}}
            elif path == "/conversations.history":
                body = {
                    "ok": True,
                    "messages": [{"ts": "100.000001", "text": state["text"]}],
                    "response_metadata": {"next_cursor": ""},
                    "has_more": False,
                }
            else:
                self.send_error(404)
                return
            encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("service", ["drive", "slack"])
def test_framework_injects_configuration_and_ingests_real_provider_contract(api, tmp_path, service):
    base, state = api
    transport = HttpTransport(base, "app-supplied-token", allow_insecure_localhost=True)
    if service == "drive":
        provider = GoogleDriveProvider(
            "app-supplied-token", account_id="account", folder_id="folder", transport=transport
        )
        root_uri, item_uri = provider.root_uri, provider.uri("item")

        def prepare(file):
            return index_default(parse_auto(file), readers=("*",))

    else:
        provider = SlackProvider(
            "app-supplied-token", workspace_id="T1", channel_ids=("C1",), transport=transport
        )
        root_uri, item_uri = provider.uri("C1"), provider.uri("C1", "100.000001")

        def prepare(file):
            message = json.loads(file.content)
            return index_default((Document(file.ref.key, message["text"]),), readers=("*",))

    source = Resources(provider, root_uri)
    runtime = Runtime(tmp_path / "state.db", [App(service, source, prepare)])
    runtime.sync()
    assert runtime.search(service, "connected", Principal())
    assert "app-supplied-token" not in source.identity
    assert not runtime.apps[service].writable
    old_version = source.current(item_uri).version
    state.update(text="updated knowledge", version="2")
    runtime.sync()
    assert runtime.search(service, "updated", Principal())
    assert source.current(item_uri).version != old_version
    assert all(token == "Bearer app-supplied-token" for _, token in state["requests"])
