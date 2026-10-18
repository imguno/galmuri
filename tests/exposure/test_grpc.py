import pytest

from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.grpc import GrpcAdapter
from galmuri.exposure.service import Service

from .fakes import FakeRuntime


def test_grpc_real_protobuf_roundtrip_and_authentication():
    grpc = pytest.importorskip("grpc")
    from google.protobuf.json_format import MessageToDict, ParseDict
    from google.protobuf.struct_pb2 import Struct

    adapter = GrpcAdapter(
        Service(FakeRuntime()),
        port=0,
        authenticator=TokenAuthenticator(
            {
                "reader-token": Principal("reader"),
            }
        ),
    )
    with adapter.server() as (_, port), grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        call = channel.unary_unary(
            "/galmuri.v1.Exposure/Call",
            request_serializer=Struct.SerializeToString,
            response_deserializer=Struct.FromString,
        )
        command = ParseDict(
            {
                "operation": "search",
                "params": {
                    "app": "readonly",
                    "query": "hello",
                    "limit": 2,
                },
            },
            Struct(),
        )
        result = MessageToDict(call(command, metadata=(("authorization", "Bearer reader-token"),)))
        assert result["ok"] is True
        assert result["result"][0]["text"] == "Result: hello"
        assert MessageToDict(call(command))["error"]["code"] == "unauthenticated"
        describe = channel.unary_unary(
            "/galmuri.v1.Exposure/Describe",
            request_serializer=Struct.SerializeToString,
            response_deserializer=Struct.FromString,
        )
        result = MessageToDict(
            describe(
                ParseDict({"app": "readonly"}, Struct()),
                metadata=(("authorization", "Bearer reader-token"),),
            )
        )
        assert result["result"]["name"] == "readonly"
