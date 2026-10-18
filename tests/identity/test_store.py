from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from argon2 import Type, extract_parameters

from galmuri.identity import AuthenticationError, IdentityError, IdentityStore

PASSWORD = "a sufficiently long password"


@pytest.fixture
def store(tmp_path):
    return IdentityStore(tmp_path / "identity.sqlite")


def account(store, administrator=False):
    return store.create_user("Alice", PASSWORD, administrator=administrator)


def test_directory_immutable_ids_and_normalized_uniqueness(store):
    user = account(store)
    group = store.create_group("Developers")
    assert len(user["id"]) == len(group["id"]) == 36
    assert user["id"] != group["id"]
    assert user["enabled"] and not user["administrator"]
    assert set(user) == {"id", "username", "enabled", "administrator", "root"}
    assert not user["root"]
    with pytest.raises(IdentityError):
        store.create_user("  ＡＬＩＣＥ ", PASSWORD)
    with pytest.raises(IdentityError):
        store.create_group("developers")
    store.add_member(group["id"], user["id"])
    store.add_member(group["id"], user["id"])
    assert store.members(group["id"]) == [user]
    assert store.list_groups() == [group]
    store.remove_member(group["id"], user["id"])
    assert store.members(group["id"]) == []
    with pytest.raises(IdentityError):
        store.add_member(group["id"], "missing")


@pytest.mark.parametrize("password", ["short", "a" * 1025, None])
def test_password_minimum_and_bounds(store, password):
    with pytest.raises(IdentityError) as error:
        store.create_user("Alice", password)
    assert "short" not in str(error.value)


def test_argon2id_and_no_persisted_raw_secrets(store):
    user = account(store)
    credential = store.login("alice", PASSWORD)
    with store.db.connection() as connection:
        stored_user = connection.execute("SELECT * FROM identity_users").fetchone()
        stored_credential = connection.execute("SELECT * FROM identity_credentials").fetchone()
    parameters = extract_parameters(stored_user["password_hash"])
    assert parameters.type == Type.ID
    assert parameters.memory_cost >= 19456 and parameters.time_cost >= 2
    assert PASSWORD not in repr(dict(stored_user))
    assert credential["token"] not in repr(dict(stored_credential))
    assert len(stored_credential["digest"]) == 64
    assert credential["user_id"] == user["id"]
    assert credential["kind"] == "session"


def test_live_group_membership_and_no_admin_document_bypass(store):
    user = account(store, administrator=True)
    group = store.create_group("team")
    issued = store.login("alice", PASSWORD)
    principal = store.authenticate(issued["token"])
    assert principal.subject == user["id"]
    assert principal.administrator
    assert not principal.root
    assert not principal.matches(("group:" + group["id"],))
    assert not principal.matches(("user:another",))
    store.add_member(group["id"], user["id"])
    assert principal.matches(("group:" + group["id"],))
    assert group["id"] in principal.groups
    store.remove_member(group["id"], user["id"])
    assert not principal.matches(("group:" + group["id"],))
    assert principal.matches(("user:" + user["id"],))
    assert not principal.matches(("user:alice",))


def test_scopes_app_restrictions_and_raw_secret_only_once(store):
    user = account(store, administrator=True)
    token = store.issue_token(user["id"], "LLM", scopes=("read",), apps=("knowledge",))
    principal = store.authenticate(token["token"])
    assert principal.authorize("read", "knowledge")
    assert not principal.authorize("write", "knowledge")
    assert not principal.authorize("read", "other")
    assert not principal.administrator
    assert "token" not in store.list_tokens(user["id"])[0]
    assert token["token"] not in repr(principal)
    store.revoke_token(token["id"], user_id=user["id"])
    assert not principal.authorize("read", "knowledge")
    assert not principal.matches(("*",))
    assert not principal.is_authenticated
    assert not store.list_tokens(user["id"])[0]["active"]
    with pytest.raises(AuthenticationError) as error:
        store.authenticate(token["token"])
    assert token["token"] not in str(error.value)


def test_expiry_exact_boundary_and_lifetime_validation(tmp_path):
    now = [100.0]
    store = IdentityStore(tmp_path / "identity.sqlite", clock=lambda: now[0])
    user = account(store)
    issued = store.issue_token(user["id"], "short lived", ttl=10)
    principal = store.authenticate(issued["token"])
    now[0] = 110.0
    assert not principal.matches(("*",))
    assert not principal.authorize("read")
    for ttl in (0, -1, True, 1.5, 365 * 86400 + 1):
        with pytest.raises(IdentityError):
            store.issue_token(user["id"], "bad", ttl=ttl)
    with pytest.raises(IdentityError):
        store.login("Alice", PASSWORD, ttl=86401)


def test_password_change_and_disable_invalidate_old_credentials_permanently(store):
    user = account(store)
    session = store.login("Alice", PASSWORD)
    token = store.issue_token(user["id"], "LLM")
    principal = store.authenticate(session["token"])
    store.change_password(user["id"], "a different sufficiently long password")
    assert not principal.matches(("*",))
    with pytest.raises(AuthenticationError):
        store.authenticate(token["token"])
    issued = store.login("Alice", "a different sufficiently long password")
    store.set_user_enabled(user["id"], False)
    store.set_user_enabled(user["id"], True)
    with pytest.raises(AuthenticationError):
        store.authenticate(issued["token"])


def test_revocation_owner_guard_and_idempotence(store):
    user = account(store)
    other = store.create_user("Bob", PASSWORD)
    issued = store.issue_token(user["id"], "LLM")
    with pytest.raises(IdentityError):
        store.revoke_token(issued["id"], user_id=other["id"])
    assert store.authenticate(issued["token"]).is_authenticated
    store.revoke_token(issued["id"], user_id=user["id"])
    store.revoke_token(issued["id"], user_id=user["id"])


def test_shared_throttling_and_window_reset(tmp_path):
    now = [100.0]
    path = tmp_path / "identity.sqlite"
    first, second = (IdentityStore(path, clock=lambda: now[0]) for _ in range(2))
    account(first)
    for _ in range(10):
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            first.login("Alice", "a wrong long enough password", rate_key="peer")
    with pytest.raises(AuthenticationError, match="temporarily"):
        second.login("Alice", PASSWORD, rate_key="another peer")
    now[0] += 900
    assert second.authenticate(second.login("Alice", PASSWORD)["token"]).is_authenticated


def test_parallel_login_reservations_bound_expensive_verification(store):
    account(store)
    original = store.hasher
    calls = []

    class Hasher:
        def verify(self, encoded, password):
            calls.append(1)
            return original.verify(encoded, password)

    store.hasher = Hasher()

    def attempt(_):
        try:
            store.login("Alice", "a wrong long enough password", rate_key="peer")
        except AuthenticationError:
            pass

    with ThreadPoolExecutor(max_workers=15) as pool:
        list(pool.map(attempt, range(20)))
    assert len(calls) == 10


@pytest.mark.parametrize("action", ["password", "disable"])
def test_account_mutation_during_hash_verification_prevents_session_issuance(store, action):
    user = account(store)
    entered, proceed = Event(), Event()
    original = store.hasher

    class Hasher:
        hash = original.hash

        def verify(self, encoded, password):
            result = original.verify(encoded, password)
            entered.set()
            assert proceed.wait(5)
            return result

    store.hasher = Hasher()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(store.login, "Alice", PASSWORD)
        assert entered.wait(5)
        if action == "password":
            store.change_password(user["id"], "another sufficiently long password")
        else:
            store.set_user_enabled(user["id"], False)
        proceed.set()
        with pytest.raises(AuthenticationError):
            pending.result()
    with store.db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM identity_credentials").fetchone()[0] == 0


@pytest.mark.parametrize(
    "scopes,apps",
    [
        (("root",), ("*",)),
        ((), ("*",)),
        (("read",), ()),
        (("read",), ("*", "other")),
        ("read", ("*",)),
    ],
)
def test_invalid_token_restrictions(store, scopes, apps):
    user = account(store)
    with pytest.raises(IdentityError):
        store.issue_token(user["id"], "bad", scopes=scopes, apps=apps)


def test_root_acl_bypass_preserves_credential_scope_and_app_restrictions(store):
    user = store.create_user("root", PASSWORD, root=True)
    assert user["root"] and user["administrator"]
    issued = store.issue_token(user["id"], "read-only root", apps=("knowledge",))
    principal = store.authenticate(issued["token"])
    assert principal.root
    assert principal.matches(())
    assert principal.matches(("user:unrelated", "group:unrelated"))
    assert principal.authorize("read", "knowledge")
    assert not principal.authorize("read", "another")
    assert not principal.authorize("write", "knowledge")
    assert not principal.authorize("manage", "knowledge")
    assert not principal.administrator
    session = store.authenticate(store.login("root", PASSWORD)["token"])
    assert session.root and session.administrator


@pytest.mark.parametrize("action", ["revoke", "expire", "disable", "password"])
def test_root_authority_revalidates_before_empty_and_public_grants(tmp_path, action):
    now = [100.0]
    store = IdentityStore(tmp_path / "identity.sqlite", clock=lambda: now[0])
    user = store.create_user("root", PASSWORD, root=True)
    issued = store.issue_token(user["id"], "short lived", ttl=10)
    principal = store.authenticate(issued["token"])
    assert principal.root and principal.matches(())
    if action == "revoke":
        store.revoke_token(issued["id"])
    elif action == "expire":
        now[0] = 110.0
    elif action == "disable":
        store.set_user_enabled(user["id"], False)
    else:
        store.change_password(user["id"], "a different sufficiently long password")
    assert not principal.root
    assert not principal.matches(())
    assert not principal.matches(("*",))
    assert not principal.authorize("read", "knowledge")
    with pytest.raises(AuthenticationError):
        store.authenticate(issued["token"])


def test_existing_directory_migration_never_promotes_administrator(tmp_path):
    path = tmp_path / "identity.sqlite"
    original = IdentityStore(path)
    user = original.create_user("old administrator", PASSWORD, administrator=True)
    group = original.create_group("old team")
    original.add_member(group["id"], user["id"])
    session = original.login("old administrator", PASSWORD)
    # Reproduce the previous released schema while preserving directory/credential data.
    with original.db.transaction() as connection:
        connection.execute("ALTER TABLE identity_users DROP COLUMN is_root")
    migrated = IdentityStore(path)
    record = migrated.list_users()[0]
    assert record["id"] == user["id"] and record["administrator"] and not record["root"]
    principal = migrated.authenticate(session["token"])
    assert principal.administrator and not principal.root
    assert principal.groups == frozenset({group["id"]})
    assert not principal.matches(())
    assert migrated.authenticate(migrated.login("old administrator", PASSWORD)["token"])
    # Migration is idempotent and can be opened concurrently by worker processes.
    with ThreadPoolExecutor(max_workers=3) as pool:
        stores = list(pool.map(lambda _: IdentityStore(path), range(3)))
    assert all(not item.list_users()[0]["root"] for item in stores)


def test_root_flag_rejects_non_boolean_authority(store):
    with pytest.raises(IdentityError):
        store.create_user("root", PASSWORD, root="true")


def test_database_injection_preserves_clock_and_rejects_ambiguous_storage(tmp_path):
    from galmuri.storage.database import Database

    database = Database(tmp_path / "injected.sqlite")
    store = IdentityStore(database=database)
    assert store.db is database
    assert store.clock == database.now
    account(store)
    assert IdentityStore(database=database).list_users() == store.list_users()

    def explicit_clock():
        return 123.0

    assert IdentityStore(database=database, clock=explicit_clock).clock is explicit_clock
    with pytest.raises(TypeError, match="not both"):
        IdentityStore(tmp_path / "other.sqlite", database=database)
    with pytest.raises(TypeError, match="required"):
        IdentityStore()
