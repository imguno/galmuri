"""Grouped configuration is an immutable boundary before persistence or source IO."""

from dataclasses import FrozenInstanceError, replace

import pytest

from galmuri import App, DatabaseConfig
from galmuri.apps import DatabaseConfig as AppsDatabaseConfig
from galmuri.apps.resolution import resolve_app
from galmuri.runtime import Runtime
from tests.runtime.test_lifecycle import Source


def test_default_selection_and_shared_configuration_survive_resolution(tmp_path):
    assert AppsDatabaseConfig is DatabaseConfig
    assert App("default", Source()).database == DatabaseConfig(alias="default")
    selection = DatabaseConfig(alias="postgres", namespace="team")
    first = App("first", Source(), database=selection, retrieval=None)
    second = App("second", Source(), database=selection, retrieval=None)
    with pytest.raises(FrozenInstanceError):
        selection.namespace = "other"
    changed = replace(first, database=replace(selection, namespace="other"))
    assert second.database is selection
    assert changed.database.namespace == "other"
    assert resolve_app(first, tmp_path / "state.sqlite").database is selection


@pytest.mark.parametrize(
    "values",
    [
        {"alias": ""},
        {"alias": None},
        {"alias": []},
        {"alias": "x" * 101},
        {"namespace": ""},
        {"namespace": 12},
        {"namespace": []},
        {"namespace": "x" * 64},
    ],
)
def test_invalid_database_values_fail_at_configuration_boundary(values):
    with pytest.raises(ValueError):
        DatabaseConfig(**values)


@pytest.mark.parametrize("selection", ["archive", {"alias": "archive"}, None])
def test_obsolete_or_untyped_selection_is_not_silently_ignored(tmp_path, selection):
    with pytest.raises(TypeError, match="DatabaseConfig"):
        App("test", Source(), database=selection)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "selection", [DatabaseConfig(alias="archive"), DatabaseConfig(namespace="team")]
)
def test_direct_runtime_requires_backend_for_nondefault_selection(tmp_path, selection):
    app = App("test", Source(), database=selection)
    with pytest.raises(ValueError, match="configured backend"):
        Runtime(tmp_path / "state.sqlite", [app])
    assert not list(tmp_path.iterdir())
