"""Semantic modes and document grants survive actual HTTP and gRPC transport."""

import json
from urllib.request import Request, urlopen

import pytest

from galmuri import App, Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.service import Service
from galmuri.ingestion.indexing import index_default
from galmuri.ingestion.parsers import parse_auto
from galmuri.retrieval import (
    EmbeddingProvider,
    EmbeddingSpec,
    RetrievalConfig,
    SQLiteVectorStore,
)
from galmuri.runtime import Runtime
from galmuri.sources.local import LocalFiles


class TestEmbedding(EmbeddingProvider):
    """Deterministic contract collaborator; real neural evidence lives separately."""

    __test__ = False

    @property
    def spec(self):
        return EmbeddingSpec("transport-test", "fixed", 2, "1")

    def embed_documents(self, texts):
        return tuple((1.0, 0.0) for _ in texts)

    def embed_query(self, text):
        return (1.0, 0.0)


@pytest.fixture
def semantic_service(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.md").write_text("Car maintenance instructions", encoding="utf-8")

    def prepare(file):
        return index_default(parse_auto(file), readers=("group:dev",))

    runtime = Runtime(
        tmp_path / "state.sqlite",
        [
            App(
                "team",
                LocalFiles(source),
                prepare,
                retrieval=RetrievalConfig(
                    embedding=TestEmbedding(),
                    store=SQLiteVectorStore(tmp_path / "vectors.sqlite"),
                ),
            )
        ],
    )
    runtime.sync()
    auth = TokenAuthenticator(
        {
            "dev": Principal("dev", frozenset({"dev"})),
            "outsider": Principal("outsider", administrator=True),
        }
    )
    return Service(runtime), auth


def test_http_get_and_post_preserve_semantic_mode_and_grants(semantic_service):
    from galmuri.exposure.http import HttpAdapter

    service, auth = semantic_service
    with HttpAdapter(service, authenticator=auth, port=0).server() as server:
        base = f"http://127.0.0.1:{server.server_port}"

        def search(mode, token, *, get=False):
            params = {"app": "team", "query": "automobile", "mode": mode}
            request = Request(
                base
                + (f"/api/search?app=team&query=automobile&mode={mode}" if get else "/api/call"),
                data=None
                if get
                else json.dumps({"operation": "search", "params": params}).encode(),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        assert search("lexical", "dev")["result"] == []
        for get in (True, False):
            found = search("vector", "dev", get=get)["result"]
            assert found[0]["search_mode"] == "vector"
            assert found[0]["key"] == "private.md"
            assert search("hybrid", "outsider", get=get)["result"] == []


def test_grpc_preserves_semantic_mode_and_grants(semantic_service):
    grpc = pytest.importorskip("grpc")
    from google.protobuf.json_format import MessageToDict, ParseDict
    from google.protobuf.struct_pb2 import Struct

    from galmuri.exposure.grpc import GrpcAdapter

    service, auth = semantic_service
    with GrpcAdapter(service, authenticator=auth, port=0).server() as (_, port):
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            method = channel.unary_unary(
                "/galmuri.v1.Exposure/Call",
                request_serializer=Struct.SerializeToString,
                response_deserializer=Struct.FromString,
            )

            def search(mode, token):
                command = ParseDict(
                    {
                        "operation": "search",
                        "params": {
                            "app": "team",
                            "query": "automobile",
                            "mode": mode,
                        },
                    },
                    Struct(),
                )
                return MessageToDict(
                    method(command, metadata=(("authorization", "Bearer " + token),))
                )

            assert search("lexical", "dev")["result"] == []
            found = search("hybrid", "dev")["result"]
            assert found[0]["search_mode"] == "hybrid"
            assert found[0]["key"] == "private.md"
            assert search("vector", "outsider")["result"] == []
