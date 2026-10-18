"""Actual protobuf gRPC transport with optional dependency loading."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.service.errors import ExposureError, failure


class GrpcAdapter:
    def __init__(
        self,
        service,
        *,
        authenticator=None,
        host="127.0.0.1",
        port=50051,
        max_body_bytes=1048576,
        workers=8,
        tls_terminated=False,
    ):
        self.service = service
        self.authenticator = authenticator or TokenAuthenticator()
        self.host, self.port = host, port
        self.max_body_bytes, self.workers = max_body_bytes, workers
        identity = getattr(service, "identity", None)
        if identity is not None:
            from galmuri.exposure.auth.accounts import AccountAuthenticator

            if host not in {"127.0.0.1", "localhost", "::1"} and tls_terminated is not True:
                raise ValueError(
                    "Account gRPC requires loopback or an explicitly configured TLS proxy"
                )
            if authenticator is not None and (
                not isinstance(authenticator, AccountAuthenticator)
                or authenticator.store is not identity
            ):
                raise ValueError("Identity gRPC requires its account authenticator")
            self.authenticator = authenticator or AccountAuthenticator(
                identity, allow_anonymous=True
            )

    def build_server(self):
        try:
            import grpc
            from google.protobuf.json_format import MessageToDict, ParseDict
            from google.protobuf.struct_pb2 import Struct
        except ImportError:
            raise RuntimeError("Install galmuri[grpc] to use the gRPC adapter") from None

        def invoke(request, context, describe=False):
            try:
                authorization = [
                    value for key, value in context.invocation_metadata() if key == "authorization"
                ]
                if len(authorization) > 1:
                    raise ExposureError("unauthenticated", "Duplicate authorization metadata")
                principal = self.authenticator.authenticate(
                    authorization[0] if authorization else None
                )
                payload = MessageToDict(request)
                if describe:
                    response = self.service.call("describe", payload, principal)
                elif payload.keys() - {"operation", "params"}:
                    response = failure("invalid_request", "Invalid command envelope")
                else:
                    params = payload.get("params", {})
                    if isinstance(params, dict):
                        for field in ("limit", "offset", "expected_revision"):
                            value = params.get(field)
                            if isinstance(value, float) and value.is_integer():
                                params[field] = int(value)
                    response = self.service.call(payload.get("operation"), params, principal)
            except ExposureError as exc:
                response = failure(exc.code, str(exc))
            return ParseDict(response, Struct())

        server = grpc.server(
            ThreadPoolExecutor(max_workers=self.workers),
            options=[
                ("grpc.max_receive_message_length", self.max_body_bytes),
                ("grpc.max_send_message_length", self.max_body_bytes),
            ],
        )
        server.add_generic_rpc_handlers(
            (
                grpc.method_handlers_generic_handler(
                    "galmuri.v1.Exposure",
                    {
                        "Call": grpc.unary_unary_rpc_method_handler(
                            invoke,
                            request_deserializer=Struct.FromString,
                            response_serializer=Struct.SerializeToString,
                        ),
                        "Describe": grpc.unary_unary_rpc_method_handler(
                            lambda request, context: invoke(request, context, True),
                            request_deserializer=Struct.FromString,
                            response_serializer=Struct.SerializeToString,
                        ),
                    },
                ),
            )
        )
        port = server.add_insecure_port(f"{self.host}:{self.port}")
        if not port:
            raise OSError("Could not bind the gRPC listener")
        return server, port

    @contextmanager
    def server(self):
        server, port = self.build_server()
        server.start()
        try:
            yield server, port
        finally:
            server.stop(grace=2).wait(timeout=5)

    def serve_forever(self):
        with self.server() as (server, _):
            server.wait_for_termination()

    def run(self):
        self.serve_forever()
