"""Database inheritance and physical targets determine App persistence defaults."""

from types import SimpleNamespace

import pytest

from galmuri import App, DatabaseConfig
from galmuri.configuration.storage import project_backends
from tests.runtime.test_lifecycle import Source


def test_default_aliases_coalesce_and_other_sqlite_files_get_distinct_vectors(tmp_path):
    settings = SimpleNamespace(
        DATABASES={
            "default": {"ENGINE": "sqlite", "NAME": "state.sqlite"},
            "same": {"ENGINE": "sqlite", "NAME": "state.sqlite"},
            "archive": {"ENGINE": "sqlite", "NAME": "archive.sqlite"},
            "other": {"ENGINE": "sqlite", "NAME": "archive.db"},
        }
    )
    # Same physical DB behaves identically even if the non-default alias is first.
    apps = [
        App("same", Source(), database=DatabaseConfig(alias="same")),
        App("primary", Source()),
        App("archive", Source(), database=DatabaseConfig(alias="archive")),
        App("other", Source(), database=DatabaseConfig(alias="other")),
    ]
    location, routed, _ = project_backends(settings, tmp_path, apps)
    assert location == tmp_path / "state.sqlite"
    assert routed["same"] is routed["primary"]
    assert routed["primary"].default_store()._database.path == tmp_path / "vectors.sqlite3"
    paths = {backend.default_store()._database.path for backend in routed.values()}
    assert len(paths) == 3
    assert tmp_path / "archive.sqlite.vectors.sqlite3" in paths
    assert tmp_path / "archive.db.vectors.sqlite3" in paths


@pytest.mark.parametrize(
    "settings,app,message",
    [
        (SimpleNamespace(DATABASES={}), App("test", Source()), "requires a default"),
        (
            SimpleNamespace(),
            App("test", Source(), database=DatabaseConfig(alias="absent")),
            "Unknown database alias",
        ),
        (
            SimpleNamespace(),
            App("test", Source(), database=DatabaseConfig(namespace="tenant")),
            "does not support",
        ),
    ],
)
def test_invalid_target_is_rejected_before_runtime_is_opened(tmp_path, settings, app, message):
    with pytest.raises(ValueError, match=message):
        project_backends(settings, tmp_path, [app])
    assert not list(tmp_path.iterdir())


def test_legacy_database_path_remains_the_default(tmp_path):
    location, routed, _ = project_backends(
        SimpleNamespace(DATABASE="custom.sqlite"), tmp_path, [App("test", Source())]
    )
    assert location == routed["test"].path == tmp_path / "custom.sqlite"
