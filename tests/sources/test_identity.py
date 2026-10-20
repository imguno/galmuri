from galmuri.sources.local import LocalFiles, ReadOnlyFiles


def test_local_identity_tracks_resource_not_implementation_class(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert LocalFiles(a).identity == ReadOnlyFiles(a).identity
    assert LocalFiles(a).identity != LocalFiles(b).identity
