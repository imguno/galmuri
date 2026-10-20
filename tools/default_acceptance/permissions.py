"""Exercise live directory authorization against already-published neural vectors."""

import secrets
import time

from galmuri import Principal
from galmuri.exposure.service import Service
from galmuri.identity import AuthenticationError, IdentityStore

from .observations import vectors


def exercise(runtime, directory_path, store_path, clinic, query, require, record):
    """Change ACL/membership/credentials without rebuilding an embedding generation."""
    clock = [time.time()]
    directory = IdentityStore(directory_path, clock=lambda: clock[0])
    user = directory.create_user("reader", secrets.token_urlsafe(32))
    administrator = directory.create_user("operator", secrets.token_urlsafe(32), administrator=True)
    group = directory.create_group("clinical-readers")
    issued = directory.issue_token(user["id"], "acceptance MCP", apps=("sample",))
    admin_token = directory.issue_token(
        administrator["id"], "acceptance operator", scopes=("read", "manage"), apps=("sample",)
    )
    member = directory.authenticate(issued["token"])
    admin = directory.authenticate(admin_token["token"])
    before_vectors = vectors(store_path)
    before_jobs = [
        (item["id"], item["state"]) for item in runtime.indexing.status("sample")["jobs"]
    ]

    def contains(principal):
        return clinic["key"] in {item["key"] for item in query(principal=principal)}

    def during_store_io(principal, mutation):
        store = runtime.apps["sample"].retrieval.store
        original, calls = store.search, []

        def intercept(*args, **kwargs):
            results = original(*args, **kwargs)
            mutation()
            calls.append(True)
            return results

        store.search = intercept
        try:
            results = query(principal=principal)
            require(calls, "Authorization race did not reach actual vector store IO")
            return results
        finally:
            store.search = original

    runtime.documents.set_permissions("sample", clinic["key"], (), ())
    require(admin.administrator, "Expected an authenticated account administrator")
    require(not contains(admin), "Account administrator bypassed explicit empty document grants")
    require(not contains(Principal()), "Anonymous caller bypassed explicit empty grants")
    try:
        runtime.read("sample", clinic["key"], admin)
    except PermissionError:
        pass
    else:
        raise RuntimeError("Account administrator read explicitly denied document text")
    record("verified_administrator_has_no_document_acl_bypass")

    root = directory.create_user("root operator", secrets.token_urlsafe(32), root=True)
    root_issued = directory.issue_token(root["id"], "root reader", apps=("sample",))
    root_principal = directory.authenticate(root_issued["token"])
    service = Service(runtime, identity=directory)
    root_search = service.call(
        "search",
        {"app": "sample", "query": "몸이 좋지 않을 때 누구를 찾아가야 하나요?", "mode": "vector"},
        root_principal,
    )
    require(
        root_search["ok"] and clinic["key"] in {item["key"] for item in root_search["result"]},
        "Root account did not bypass explicit empty ACL during actual vector retrieval",
    )
    root_read = service.call(
        "read",
        {"app": "sample", "document_key": clinic["key"]},
        root_principal,
    )
    require(
        root_read["ok"] and root_read["result"]["text"] == clinic["text"],
        "Root account did not bypass explicit empty read ACL",
    )
    denied_write = service.call(
        "write",
        {
            "app": "sample",
            "document_key": clinic["key"],
            "content": "rejected",
            "expected_version": clinic["version"],
        },
        root_principal,
    )
    denied_manage = service.call("status", {"app": "sample"}, root_principal)
    require(
        not denied_write["ok"] and denied_write["error"]["code"] == "forbidden",
        "Root read-only credential escaped write scope",
    )
    require(
        not denied_manage["ok"] and denied_manage["error"]["code"] == "forbidden",
        "Root read-only credential escaped management scope",
    )
    restricted = directory.issue_token(root["id"], "another app", apps=("other",))
    denied_app = service.call(
        "search",
        {"app": "sample", "query": "clinic"},
        directory.authenticate(restricted["token"]),
    )
    require(
        not denied_app["ok"] and denied_app["error"]["code"] == "forbidden",
        "Root credential escaped app allow-list",
    )
    require(
        during_store_io(root_principal, lambda: directory.revoke_token(root_issued["id"])) == [],
        "Root authority survived credential revocation during actual vector IO",
    )
    record(
        "verified_root_acl_bypass_with_scope_app_and_mid_io_revocation_limits",
        user_id=root["id"],
        build=clinic["build"],
    )

    runtime.documents.set_permissions("sample", clinic["key"], ("group:" + group["id"],), ())
    require(not contains(member), "Account gained group rights before joining")
    directory.add_member(group["id"], user["id"])
    require(contains(member), "New directory group membership did not authorize existing principal")
    require(
        runtime.read("sample", clinic["key"], member)["text"] == clinic["text"],
        "Verified group member could not read published body",
    )
    raced = during_store_io(member, lambda: directory.remove_member(group["id"], user["id"]))
    require(
        clinic["key"] not in {item["key"] for item in raced},
        "Group removal during actual vector IO leaked document text",
    )
    require(not contains(member), "Removed group membership retained semantic document access")
    require(not contains(admin), "Administrator bypassed explicit group grants")
    require(vectors(store_path) == before_vectors, "ACL change rebuilt physical vectors")
    require(
        [(item["id"], item["state"]) for item in runtime.indexing.status("sample")["jobs"]]
        == before_jobs,
        "Membership or ACL changes generated embedding work",
    )
    record(
        "dynamic_group_membership_without_embedding_rebuild",
        user_id=user["id"],
        group_id=group["id"],
        build=clinic["build"],
        vectors=before_vectors,
    )

    # Public fallback does not rescue a credential which was explicitly presented
    # and subsequently revoked/expired: live principals revalidate before wildcard ACLs.
    runtime.documents.set_permissions("sample", clinic["key"], ("*",), ("*",))
    require(contains(Principal()), "Public document access was not restored")
    expiring = directory.issue_token(user["id"], "short lived", ttl=1)
    expired_principal = directory.authenticate(expiring["token"])
    clock[0] += 2
    require(query(principal=expired_principal) == [], "Expired credential read public vectors")
    require(
        during_store_io(member, lambda: directory.revoke_token(issued["id"])) == [],
        "Credential revocation during actual vector IO leaked public document text",
    )
    require(query(principal=member) == [], "Revoked credential read public vectors")
    for raw in (issued["token"], expiring["token"]):
        try:
            directory.authenticate(raw)
        except AuthenticationError:
            pass
        else:
            raise RuntimeError("Expired or revoked credential authenticated")
    record("expired_and_revoked_credentials_do_not_fall_back_to_public_access")
