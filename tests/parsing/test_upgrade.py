"""A built-in parsing change must not silently reuse old checkpoint identities."""

from dataclasses import replace

import pytest
from duru import ReadOnlyLocalProvider

from galmuri import App, Principal
from galmuri.parsing import ParsingConfig, parse_auto, parse_markdown
from galmuri.runtime import Runtime


def test_builtin_identity_invalidates_existing_app_and_requires_activation(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    (files / "guide.md").write_text("Section\n=======\n\nContent", encoding="utf-8")
    # This is the exact parser binding identity used before this change.
    previous = ParsingConfig(parse_auto, identity="galmuri.parsing:auto")
    app = App("docs", ReadOnlyLocalProvider(files), parser=previous, retrieval=None)
    runtime = Runtime(tmp_path / "state.db", [app])
    runtime.sync()
    revision = runtime.apps["docs"].revision
    current = replace(app, parser=ParsingConfig())
    with pytest.raises(ValueError, match="activat"):
        Runtime(runtime.database.path, [current])
    fresh = Runtime(runtime.database.path, [current], activate=True)
    assert fresh.apps["docs"].revision != revision
    assert fresh.search("docs", "Content", Principal()) == []
    fresh.sync()
    result = fresh.search("docs", "Content", Principal())
    assert result[0]["metadata"]["headings"] == [{"level": 1, "text": "Section"}]
    assert ParsingConfig(parse_markdown).identity == "galmuri.parsing:markdown:v2"
    assert ParsingConfig(parse_auto).fingerprint == ParsingConfig().fingerprint
