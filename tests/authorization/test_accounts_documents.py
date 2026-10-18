"""Real directory credentials meet current document ACLs at the service boundary."""

import pytest
from duru import LocalProvider, ReadOnlyLocalProvider

from galmuri import App, Principal
from galmuri.exposure.service import Service
from galmuri.identity import IdentityStore
from galmuri.runtime import Runtime

PASSWORD = "a synthetic strong password 123"


@pytest.fixture
def system(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    (files / "private.md").write_text("private body", encoding="utf-8")
    (files / "public.md").write_text("public body", encoding="utf-8")
    runtime = Runtime(tmp_path / "state.db", [App("docs", LocalProvider(files), retrieval=None)])
    runtime.sync()
    directory = IdentityStore(tmp_path / "accounts.db")
    root = directory.create_user("root", PASSWORD, root=True)
    admin = directory.create_user("admin", PASSWORD, administrator=True)
    member = directory.create_user("member", PASSWORD)
    group = directory.create_group("team")
    session = directory.authenticate(directory.login("root", PASSWORD)["token"])
    service = Service(runtime, identity=directory)
    records = service.call("documents", {"app": "docs"}, Principal())["result"]["items"]
    keys = {record["name"]: record["key"] for record in records}
    return runtime, directory, service, session, root, admin, member, group, keys


def token(directory, user, scopes=("read", "write"), apps=("*",)):
    credential = directory.issue_token(user["id"], "test", scopes=scopes, apps=apps)
    return directory.authenticate(credential["token"]), credential


def restrict(service, root, key, grants):
    return service.call(
        "document_permissions",
        {
            "app": "docs",
            "document_key": key,
            "readers": grants,
            "writers": grants,
            "expected_revision": 0,
        },
        root,
    )


def test_defaults_allow_anonymous_read_and_conditional_write(system):
    runtime, _, service, _, *_, keys = system
    key = keys["public.md"]
    read = service.call("read", {"app": "docs", "document_key": key}, Principal())
    assert read["ok"]
    write = service.call(
        "write",
        {
            "app": "docs",
            "document_key": key,
            "content": "updated public",
            "expected_version": read["result"]["version"],
        },
        Principal(),
    )
    assert write["ok"] and write["result"]["indexing"] == "QUEUED"
    runtime.sync()
    assert (
        service.call("read", {"app": "docs", "document_key": key}, Principal())["result"]["text"]
        == "updated public"
    )


def test_group_membership_updates_live_without_reindex_and_admin_has_no_bypass(system):
    _, directory, service, root, _, admin, member, group, keys = system
    key = keys["private.md"]
    assert restrict(service, root, key, ["group:" + group["id"]])["ok"]
    caller, _ = token(directory, member)
    administrator, _ = token(directory, admin, ("read", "write", "manage"))
    request = {"app": "docs", "document_key": key}
    assert not service.call("read", request, caller)["ok"]
    directory.add_member(group["id"], member["id"])
    assert service.call("read", request, caller)["result"]["text"] == "private body"
    directory.remove_member(group["id"], member["id"])
    assert service.call("search", {"app": "docs", "query": "private"}, caller)["result"] == []
    assert not service.call("read", request, administrator)["ok"]
    visible = service.call("documents", {"app": "docs"}, administrator)["result"]
    assert [row["name"] for row in visible["items"]] == ["public.md"]
    inventory = service.call("permission_inventory", {"app": "docs"}, administrator)
    assert inventory["ok"] and "private body" not in str(inventory)
    assert (
        service.call("permission_inventory", {"app": "docs"}, caller)["error"]["code"]
        == "forbidden"
    )


def test_root_bypasses_acl_but_not_scopes_app_limits_or_source_versions(system):
    _, directory, service, root, account, *_, keys = system
    key = keys["private.md"]
    assert restrict(service, root, key, [])["ok"]
    limited, credential = token(directory, account, scopes=("read",), apps=("docs",))
    document = service.call("read", {"app": "docs", "document_key": key}, limited)["result"]
    assert document["text"] == "private body"
    assert (
        service.call(
            "write",
            {
                "app": "docs",
                "document_key": key,
                "content": "must not write",
                "expected_version": document["version"],
            },
            limited,
        )["error"]["code"]
        == "forbidden"
    )
    other, _ = token(directory, account, apps=("elsewhere",))
    assert service.call("capabilities", {}, other)["result"] == {}
    assert (
        service.call("read", {"app": "docs", "document_key": key}, other)["error"]["code"]
        == "forbidden"
    )
    assert (
        service.call(
            "write",
            {
                "app": "docs",
                "document_key": key,
                "content": "must not write",
                "expected_version": "stale",
            },
            root,
        )["error"]["code"]
        == "conflict"
    )
    directory.revoke_token(credential["id"])
    assert (
        service.call("read", {"app": "docs", "document_key": key}, limited)["error"]["code"]
        == "unauthenticated"
    )


def test_acl_editor_rejects_unknown_identity_and_stale_revision(system):
    _, _, service, root, *_, keys = system
    key = keys["private.md"]
    assert restrict(service, root, key, ["user:alice"])["error"]["code"] == "invalid_request"
    assert restrict(service, root, key, [])["ok"]
    assert restrict(service, root, key, ["*"])["error"]["code"] == "conflict"
    spoof = service.call("read", {"app": "docs", "document_key": key, "root": True}, Principal())
    assert spoof["error"]["code"] == "invalid_request"


def test_app_scoped_manager_cannot_execute_global_management(system):
    _, directory, service, _, _, admin, *_ = system
    principal, _ = token(directory, admin, scopes=("read", "manage"), apps=("docs",))
    assert service.call("status", {"app": "docs"}, principal)["ok"]
    assert service.call("status", {}, principal)["error"]["code"] == "forbidden"


def test_root_cannot_enable_write_on_readonly_source(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    (files / "one.md").write_text("one", encoding="utf-8")
    directory = IdentityStore(tmp_path / "accounts.db")
    directory.create_user("root", PASSWORD, root=True)
    root = directory.authenticate(directory.login("root", PASSWORD)["token"])
    runtime = Runtime(
        tmp_path / "state.db", [App("docs", ReadOnlyLocalProvider(files), retrieval=None)]
    )
    runtime.sync()
    service = Service(runtime, identity=directory)
    assert "write" not in service.capabilities(root)["docs"]["operations"]
    key = service.call("documents", {"app": "docs"}, root)["result"]["items"][0]["key"]
    result = service.call(
        "write",
        {"app": "docs", "document_key": key, "content": "two", "expected_version": "1"},
        root,
    )
    assert result["error"]["code"] == "unsupported"


def test_grpc_uses_verified_accounts_and_preserves_integer_acl_revisions(system):
    grpc = pytest.importorskip("grpc")
    from google.protobuf.json_format import MessageToDict, ParseDict
    from google.protobuf.struct_pb2 import Struct

    from galmuri.exposure.auth import TokenAuthenticator
    from galmuri.exposure.grpc import GrpcAdapter

    _, directory, service, _, root, admin, *_, keys = system
    root_token = directory.issue_token(root["id"], "root grpc", scopes=("read", "manage"))
    admin_token = directory.issue_token(admin["id"], "admin grpc")
    with pytest.raises(ValueError, match="TLS proxy"):
        GrpcAdapter(service, host="0.0.0.0")
    with pytest.raises(ValueError, match="account authenticator"):
        GrpcAdapter(
            service, authenticator=TokenAuthenticator({"fake": Principal(administrator=True)})
        )
    adapter = GrpcAdapter(service, port=0)
    with adapter.server() as (_, port), grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
        invoke = channel.unary_unary(
            "/galmuri.v1.Exposure/Call",
            request_serializer=Struct.SerializeToString,
            response_deserializer=Struct.FromString,
        )

        def call(operation, params, token=None):
            metadata = (("authorization", "Bearer " + token),) if token else ()
            return MessageToDict(
                invoke(
                    ParseDict({"operation": operation, "params": params}, Struct()),
                    metadata=metadata,
                    timeout=5,
                )
            )

        key = keys["private.md"]
        assert call(
            "document_permissions",
            {
                "app": "docs",
                "document_key": key,
                "readers": [],
                "writers": [],
                "expected_revision": 0,
            },
            root_token["token"],
        )["ok"]
        assert call("documents", {"app": "docs", "offset": 0, "limit": 1})["ok"]
        read = {"app": "docs", "document_key": key}
        assert not call("read", read, admin_token["token"])["ok"]
        assert call("read", read, root_token["token"])["result"]["text"] == "private body"
        directory.revoke_token(root_token["id"])
        assert call("read", read, root_token["token"])["error"]["code"] == "unauthenticated"
