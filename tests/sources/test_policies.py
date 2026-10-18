import pytest

from galmuri.collection.policies import SyncPolicy
from galmuri.contracts.files import Change, ChangeSet, File, FileRef, SourceConflict
from galmuri.contracts.results import IngestResult


class ScanOnly:
    def read(self, ref):
        return File(ref, b"contents")

    def scan(self):
        return (FileRef("file.txt", "1"),)


def test_auto_falls_back_to_scan_and_does_not_infer_deletion():
    source = ScanOnly()
    result = SyncPolicy().discover(source, "previous")
    assert result.changes == (Change(FileRef("file.txt", "1")),)
    assert result.checkpoint == "previous"
    source.scan = lambda: ()
    assert SyncPolicy(mode="scan").discover(source, "previous").changes == ()


def test_auto_prefers_changes_and_forwards_checkpoint():
    class Changes(ScanOnly):
        def changes(self, checkpoint):
            assert checkpoint == "cursor"
            return ChangeSet((Change(FileRef("deleted", "1"), deleted=True),), "next")

    result = SyncPolicy().discover(Changes(), "cursor")
    assert result.changes[0].deleted
    assert result.checkpoint == "next"


def test_explicit_unsupported_capability_fails_instead_of_changing_policy():
    with pytest.raises(TypeError, match="changes"):
        SyncPolicy(mode="changes").validate(ScanOnly())
    with pytest.raises(TypeError, match="read"):
        SyncPolicy().validate(object())


def test_callable_class_handler_runs_after_versioned_read():
    class Handler:
        def __call__(self, file):
            assert file.text == "contents"
            return IngestResult((), ("processed",))

    result = SyncPolicy().execute(ScanOnly(), FileRef("file.txt", "1"), Handler())
    assert result.messages == ("processed",)


def test_invalid_handler_result_is_not_success():
    with pytest.raises(TypeError, match="IngestResult"):
        SyncPolicy().execute(ScanOnly(), FileRef("file.txt", "1"), lambda file: None)


def test_wrong_read_version_never_reaches_handler():
    class Stale(ScanOnly):
        def read(self, ref):
            return File(FileRef(ref.key, "2"), b"contents")

    with pytest.raises(SourceConflict):
        SyncPolicy().execute(Stale(), FileRef("file.txt", "1"), lambda file: pytest.fail())


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "unknown"},
        {"interval": 0},
        {"interval": float("inf")},
        {"retry_delay": -1},
        {"lease_seconds": 0},
        {"max_attempts": 0},
    ],
)
def test_invalid_policy_is_rejected(options):
    with pytest.raises(ValueError):
        SyncPolicy(**options)
