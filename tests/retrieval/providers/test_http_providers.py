"""Real HTTP request/response boundary tests without remote accounts."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from galmuri.retrieval import OpenAIEmbedding, ProviderError, QdrantVectorStore, VectorPoint


@contextmanager
def server(callback):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def do_PUT(self):
            self.handle_request()

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            status, payload, headers = callback(
                self.command, self.path, json.loads(body) if body else None, self.headers
            )
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def test_openai_request_ordering_query_and_secret_free_identity():
    requests = []

    def callback(method, path, body, headers):
        requests.append((method, path, body, headers["Authorization"]))
        data = [
            {"index": index, "embedding": [index + 1, 1]}
            for index in reversed(range(len(body["input"])))
        ]
        return 200, {"data": data}, {}

    with server(callback) as url:
        provider = OpenAIEmbedding("secret", dimensions=2, base_url=url)
        assert provider.embed_documents(("a", "b")) == ((1.0, 1.0), (2.0, 1.0))
        assert provider.embed_query("q") == (1.0, 1.0)
        assert provider.spec == OpenAIEmbedding("rotated", dimensions=2, base_url=url).spec
        assert "secret" not in repr(provider.spec)
        assert requests[0][0:2] == ("POST", "/embeddings")
        assert requests[0][2]["encoding_format"] == "float"
        assert requests[0][2]["dimensions"] == 2
        assert requests[0][3] == "Bearer secret"


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"index": 0, "embedding": [0, 0]}],
        [{"index": 1, "embedding": [1, 0]}],
        [{"index": 0, "embedding": [1]}],
    ],
)
def test_openai_rejects_invalid_response(data):
    with server(lambda *_: (200, {"data": data}, {})) as url:
        provider = OpenAIEmbedding("secret", dimensions=2, base_url=url)
        with pytest.raises((ProviderError, ValueError)):
            provider.embed_query("q")


def test_credentials_never_follow_redirect():
    leaked = []
    with server(lambda *args: leaked.append(args) or (200, {}, {})) as destination:
        with server(lambda *_: (302, {}, {"Location": destination + "/steal"})) as url:
            with pytest.raises(ProviderError, match="HTTP 302"):
                OpenAIEmbedding("secret", dimensions=2, base_url=url).embed_query("q")
    assert leaked == []


@pytest.mark.parametrize("secret", ["line\r\nbreak", "한글"])
def test_invalid_credentials_fail_without_echoing_them(secret):
    with pytest.raises(ValueError, match="credentials") as error:
        OpenAIEmbedding(secret, base_url="http://localhost")
    assert secret not in str(error.value)


def test_oversized_response_is_rejected(monkeypatch):
    monkeypatch.setattr("galmuri.retrieval.http.MAX_BODY", 200)
    with server(lambda *_: (200, {"data": "x" * 201}, {})) as url:
        with pytest.raises(ProviderError, match="response exceeds"):
            OpenAIEmbedding("secret", dimensions=2, base_url=url).embed_query("q")


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a",
        "https://user:secret@example.test",
        "https://example.test?secret=x",
        "https://example.test/#x",
    ],
)
def test_unsafe_provider_urls(url):
    with pytest.raises(ValueError):
        OpenAIEmbedding("secret", base_url=url)
    with pytest.raises(ValueError):
        QdrantVectorStore(url)


def test_qdrant_protocol_ensure_prefilter_points_and_idempotent_delete():
    requests = []
    exists = False
    public, private = str(uuid4()), str(uuid4())

    def callback(method, path, body, headers):
        nonlocal exists
        requests.append((method, path, body, headers.get("api-key")))
        if method == "GET":
            if not exists:
                return 404, {}, {}
            return (
                200,
                {"result": {"config": {"params": {"vectors": {"size": 2, "distance": "Cosine"}}}}},
                {},
            )
        if method == "PUT" and not path.endswith("/points?wait=true"):
            exists = True
        if path.endswith("/points/query"):
            assert body["filter"] == {"must": [{"has_id": [public]}]}
            return 200, {"result": {"points": [{"id": public, "score": 0.5}]}}, {}
        return 200, {"result": True}, {}

    with server(callback) as url:
        store = QdrantVectorStore(url, "secret")
        store.ensure("app-generation", 2)
        store.upsert("app-generation", (VectorPoint(public, (1, 0)), VectorPoint(private, (0, 1))))
        assert store.search("app-generation", (1, 0), allowed_ids=(), limit=1) == ()
        assert (
            store.search("app-generation", (1, 0), allowed_ids=(public,), limit=1)[0].id == public
        )
        store.delete("app-generation", (public,))
        store.delete("app-generation", (public,))
        assert "secret" not in store.identity
    point_body = next(
        request[2] for request in requests if request[1].endswith("/points?wait=true")
    )
    assert all(set(point) == {"id", "vector"} for point in point_body["points"])
    assert all(request[3] == "secret" for request in requests)


@pytest.mark.parametrize(
    "vectors", [{"size": 3, "distance": "Cosine"}, {"size": 2, "distance": "Dot"}, {"named": {}}]
)
def test_qdrant_never_replaces_incompatible_collection(vectors):
    methods = []

    def callback(method, *_):
        methods.append(method)
        return 200, {"result": {"config": {"params": {"vectors": vectors}}}}, {}

    with server(callback) as url:
        with pytest.raises(ProviderError):
            QdrantVectorStore(url).ensure("space", 2)
    assert methods == ["GET"]
