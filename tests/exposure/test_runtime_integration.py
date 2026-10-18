"""Adapters enforce the real runtime's publication ACL and write lifecycle."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from galmuri.apps.definition import App
from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.http import HttpAdapter
from galmuri.exposure.service import Service
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto
from galmuri.runtime import Runtime
from galmuri.sources.local import LocalFiles


def test_http_with_real_runtime_write_reindex_and_acl(tmp_path):
    sources = tmp_path / "source"
    sources.mkdir()
    (sources / "guide.md").write_text("# Team\nOriginal shared guide", encoding="utf-8")

    def process(file):
        return index_default(parse_auto(file), readers=["group:dev"], writers=["group:dev"])

    runtime = Runtime(tmp_path / "state.sqlite3", [App("team", LocalFiles(sources), process)])
    service = Service(runtime)
    admin = Principal("operator", frozenset({"dev"}), administrator=True)
    auth = TokenAuthenticator({"operator": admin, "outsider": Principal("outsider")})
    adapter = HttpAdapter(service, authenticator=auth, port=0)
    with adapter.server() as server:
        url = f"http://127.0.0.1:{server.server_port}/api/call"

        def call(operation, params, token="operator"):
            request = Request(
                url,
                data=json.dumps({"operation": operation, "params": params}).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=5) as response:
                    return json.load(response)
            except HTTPError as response:
                return json.load(response)

        assert call("sync", {"app": "team"})["ok"]
        document = call("read", {"app": "team", "document_key": "guide.md"})["result"]
        assert "Original" in document["text"]
        assert (
            call("read", {"app": "team", "document_key": "guide.md"}, "outsider")["error"]["code"]
            == "forbidden"
        )
        assert call("search", {"app": "team", "query": "guide"}, "outsider")["result"] == []
        written = call(
            "write",
            {
                "app": "team",
                "document_key": "guide.md",
                "content": "# Team\nUpdated shared guide",
                "expected_version": document["version"],
            },
        )
        assert written["result"]["indexing"] == "QUEUED"
        assert call("sync", {"app": "team"})["ok"]
        assert call("search", {"app": "team", "query": "Updated"})["result"]
        conflict = call(
            "write",
            {
                "app": "team",
                "document_key": "guide.md",
                "content": "stale",
                "expected_version": document["version"],
            },
        )
        assert conflict["error"]["code"] == "conflict"
