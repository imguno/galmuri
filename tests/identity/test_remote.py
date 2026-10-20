"""Shared account state and race guarantees against a real PostgreSQL service."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from galmuri.identity import AuthenticationError, IdentityError, IdentityStore
from galmuri.storage.postgres import PostgresDatabase

PASSWORD = "a sufficiently long password"


@pytest.fixture
def remote():
    dsn = os.environ.get("FRAMEWORK_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set FRAMEWORK_POSTGRES_DSN for real PostgreSQL identity contracts")
    driver = pytest.importorskip("psycopg")
    schema = "identity_test_" + uuid.uuid4().hex
    database = PostgresDatabase(dsn, schema=schema)
    first = IdentityStore(database=database)
    second = IdentityStore(database=PostgresDatabase(dsn, schema=schema))
    try:
        yield first, second
    finally:
        with driver.connect(dsn, autocommit=True) as connection:
            connection.execute(
                driver.sql.SQL("DROP SCHEMA {} CASCADE").format(driver.sql.Identifier(schema))
            )


def test_remote_directory_credential_revocation_and_live_groups(remote):
    first, second = remote
    user = first.create_user("Alice", PASSWORD, administrator=True)
    group = second.create_group("Developers")
    with pytest.raises(IdentityError, match="already exists"):
        second.create_user("alice", PASSWORD)
    with pytest.raises(IdentityError, match="does not exist"):
        second.add_member(group["id"], "missing")
    issued = first.issue_token(user["id"], "Reader", apps=("knowledge",))
    principal = second.authenticate(issued["token"])
    assert not principal.matches(("group:" + group["id"],))
    first.add_member(group["id"], user["id"])
    second.add_member(group["id"], user["id"])
    assert principal.matches(("group:" + group["id"],))
    assert second.members(group["id"]) == [user]
    first.remove_member(group["id"], user["id"])
    assert not principal.matches(("group:" + group["id"],))
    assert principal.authorize("read", "knowledge")
    assert not principal.authorize("write", "knowledge")
    assert not principal.authorize("read", "other")
    assert not principal.administrator
    first.revoke_token(issued["id"])
    assert not principal.matches(("*",))
    assert not second.list_tokens(user["id"])[0]["active"]


@pytest.mark.parametrize("action", ["password", "disable"])
def test_remote_account_generation_invalidates_root_authority(remote, action):
    first, second = remote
    user = first.create_user("Root", PASSWORD, root=True)
    issued = first.login("root", PASSWORD)
    principal = second.authenticate(issued["token"])
    assert principal.root and principal.matches(()) and principal.administrator
    if action == "password":
        first.change_password(user["id"], "another sufficiently long password")
    else:
        first.set_user_enabled(user["id"], False)
        first.set_user_enabled(user["id"], True)
    assert not principal.root
    assert not principal.matches(("*",))
    with pytest.raises(AuthenticationError):
        second.authenticate(issued["token"])


def test_remote_parallel_login_budget_is_shared_across_stores(remote):
    first, second = remote
    first.create_user("Alice", PASSWORD)
    calls, guard = [], Lock()

    class Hasher:
        def verify(self, encoded, password):
            with guard:
                calls.append(1)
            return False

    first.hasher = second.hasher = Hasher()

    def attempt(index):
        store = first if index % 2 else second
        try:
            store.login("alice", "a wrong sufficiently long password", rate_key="peer")
        except AuthenticationError:
            return
        pytest.fail("Invalid credentials unexpectedly authenticated")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(attempt, range(24)))
    assert len(calls) == 10


@pytest.mark.parametrize("action", ["password", "disable"])
def test_remote_mutation_during_password_verification_blocks_issuance(remote, action):
    first, second = remote
    user = first.create_user("Alice", PASSWORD)
    entered, proceed = Event(), Event()
    original = first.hasher

    class Hasher:
        def verify(self, encoded, password):
            valid = original.verify(encoded, password)
            entered.set()
            assert proceed.wait(10)
            return valid

    first.hasher = Hasher()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(first.login, "Alice", PASSWORD)
        assert entered.wait(10)
        try:
            if action == "password":
                second.change_password(user["id"], "another sufficiently long password")
            else:
                second.set_user_enabled(user["id"], False)
        finally:
            proceed.set()
        with pytest.raises(AuthenticationError):
            pending.result()
    with second.db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM identity_credentials").fetchone()[0] == 0


def test_remote_clock_uses_database_and_stores_no_raw_secrets(remote, monkeypatch):
    first, second = remote
    monkeypatch.setattr("time.time", lambda: 1.0)
    user = first.create_user("Alice", PASSWORD)
    issued = first.issue_token(user["id"], "Reader", ttl=60)
    assert issued["created_at"] > 1_700_000_000
    assert issued["expires_at"] - issued["created_at"] == 60
    assert second.authenticate(issued["token"]).is_authenticated
    with second.db.connection() as connection:
        stored_user = dict(connection.execute("SELECT * FROM identity_users").fetchone())
        stored_token = dict(connection.execute("SELECT * FROM identity_credentials").fetchone())
    assert PASSWORD not in repr(stored_user)
    assert issued["token"] not in repr(stored_token)
    assert len(stored_token["digest"]) == 64
