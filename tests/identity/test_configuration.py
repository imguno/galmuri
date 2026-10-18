"""Directory settings accept shared storage without breaking local extensions."""

from types import SimpleNamespace

import pytest

from galmuri.configuration.identity import directory
from galmuri.identity import IdentityStore
from galmuri.storage.database import Database


def test_disabled_directory_never_constructs_storage(tmp_path):
    assert directory(SimpleNamespace(), tmp_path) is None


def test_default_local_directory_resolves_relative_path(tmp_path):
    result = directory(SimpleNamespace(IDENTITY_DATABASE="accounts.sqlite"), tmp_path)
    assert isinstance(result, IdentityStore)
    assert result.db.path == tmp_path / "accounts.sqlite"


def test_legacy_local_directory_factory_receives_path(tmp_path):
    seen = []

    def factory(path):
        seen.append(path)
        return "custom-directory"

    settings = SimpleNamespace(IDENTITY_DATABASE="accounts.sqlite", IDENTITY_BACKEND=factory)
    assert directory(settings, tmp_path) == "custom-directory"
    assert seen == [tmp_path / "accounts.sqlite"]


def test_shared_directory_factory_receives_database_boundary(tmp_path, monkeypatch):
    configured = {"ENGINE": "postgresql", "DSN": "not-connected", "SCHEMA": "accounts"}
    database = Database(tmp_path / "accounts.sqlite")
    seen = []

    def storage(value, root):
        assert value is configured and root == tmp_path
        return database

    def factory(*, database):
        seen.append(database)
        return "shared-directory"

    monkeypatch.setattr("galmuri.configuration.identity.identity_database", storage)
    settings = SimpleNamespace(IDENTITY_DATABASE=configured, IDENTITY_BACKEND=factory)
    assert directory(settings, tmp_path) == "shared-directory"
    assert seen == [database]


def test_directory_factory_must_be_callable(tmp_path):
    settings = SimpleNamespace(IDENTITY_DATABASE="accounts.sqlite", IDENTITY_BACKEND="factory")
    with pytest.raises(TypeError, match="directory factory"):
        directory(settings, tmp_path)


def test_identity_uses_named_connection_alias_and_legacy_default(tmp_path):
    settings = SimpleNamespace(
        IDENTITY_DATABASE="accounts",
        DATABASES={"default": "runtime.sqlite", "accounts": "shared.sqlite"},
    )
    assert directory(settings, tmp_path).db.path == tmp_path / "shared.sqlite"
    settings = SimpleNamespace(IDENTITY_DATABASE="default", DATABASE="old-runtime.sqlite")
    assert directory(settings, tmp_path).db.path == tmp_path / "old-runtime.sqlite"
