"""Malformed plugin or legacy ACL values must never turn a substring into a grant."""

import json
from collections import UserDict
from types import MappingProxyType

import pytest

from galmuri import Principal
from galmuri.contracts.grants import normalize_grants
from galmuri.identity import IdentityStore
from tests.retrieval.test_projection import fixture


@pytest.mark.parametrize("grants", ["user:alice*", "*", {"*": True}, ["*", 1], None])
def test_unverified_principal_does_not_accept_malformed_grants(grants):
    assert not Principal("alice").matches(grants)


@pytest.mark.parametrize(
    "grants", [{"*": False}, UserDict({"*": False}), MappingProxyType({"*": False})]
)
def test_mapping_keys_cannot_become_public_grants(grants):
    with pytest.raises(TypeError, match="Permissions"):
        normalize_grants(grants)


def test_verified_account_requires_a_collection_of_exact_grants(tmp_path):
    store = IdentityStore(tmp_path / "accounts.db")
    user = store.create_user("alice", "test password with enough length")
    issued = store.login("alice", "test password with enough length")
    principal = store.authenticate(issued["token"])
    grant = "user:" + user["id"]
    assert principal.matches((grant,))
    assert not principal.matches(grant)
    assert not principal.matches(grant + "*")
    assert not principal.matches({"*": True})


def test_legacy_malformed_stored_acl_fails_closed_for_read_and_search(tmp_path):
    runtime, _, _, _ = fixture(tmp_path)
    runtime.sync()
    with runtime.database.transaction() as connection:
        connection.execute("UPDATE documents SET readers=?", (json.dumps("user:alice*"),))
    with pytest.raises(PermissionError):
        runtime.read("sample", "doc", Principal())
    assert runtime.search("sample", "content", Principal(), mode="lexical") == []
    assert runtime.search("sample", "content", Principal(), mode="vector") == []


@pytest.mark.parametrize("readers,writers", [("user:alice*", ()), ((), "user:alice*")])
def test_invalid_acl_update_does_not_mutate_permissions_or_generation(tmp_path, readers, writers):
    runtime, _, _, _ = fixture(tmp_path)
    runtime.sync()
    with runtime.database.connection() as connection:
        before = dict(connection.execute("SELECT * FROM documents").fetchone())
        generation = connection.execute("SELECT acl_generation FROM source_refs").fetchone()[0]
    with pytest.raises(TypeError, match="Permissions"):
        runtime.documents.set_permissions("sample", "doc", readers, writers)
    with runtime.database.connection() as connection:
        assert dict(connection.execute("SELECT * FROM documents").fetchone()) == before
        assert (
            connection.execute("SELECT acl_generation FROM source_refs").fetchone()[0] == generation
        )
