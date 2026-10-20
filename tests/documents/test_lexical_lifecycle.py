"""The lexical projection shares publication rollback and durable upgrade state."""

import pytest

from galmuri import Principal
from galmuri.documents.lexical import LexicalIndex, migration
from galmuri.documents.lexical.projection import retire_app, retire_source

from .helpers import publish, table


def test_update_delete_and_app_retirement_keep_statistics_consistent(database):
    with database.transaction() as connection:
        publish(connection, "one", "old old shared")
        publish(connection, "two", "shared retained")
    with database.transaction() as connection:
        publish(connection, "one", "new shared")
    assert {row["term"] for row in table(database, "lexical_terms")} == {
        "w:new",
        "w:shared",
        "w:retained",
    }
    with database.transaction() as connection:
        retire_source(connection, "docs", "one")
    assert LexicalIndex(database).search("docs", "new", Principal()) == []
    assert table(database, "lexical_corpora") == [
        {"app": "docs", "document_count": 1, "total_length": 2}
    ]
    with database.transaction() as connection:
        retire_app(connection, "docs")
    for name in ("lexical_postings", "lexical_documents", "lexical_terms", "lexical_corpora"):
        assert table(database, name) == []


def test_failed_publication_transaction_restores_body_postings_and_counts(database):
    with database.transaction() as connection:
        publish(connection, "one", "original")
    original = {
        name: table(database, name)
        for name in ("documents", "lexical_postings", "lexical_terms", "lexical_corpora")
    }
    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            publish(connection, "one", "replacement")
            raise RuntimeError("failure after publishing postings")
    assert all(table(database, name) == rows for name, rows in original.items())
    assert LexicalIndex(database).search("docs", "original", Principal())[0]["key"] == "one"
    assert LexicalIndex(database).search("docs", "replacement", Principal()) == []


def test_upgrade_backfills_current_documents_once_and_failure_rolls_back(database, monkeypatch):
    with database.transaction() as connection:
        publish(connection, "current", "한국어 검색", indexed=False)
        publish(connection, "another", "another current document", indexed=False)
        publish(connection, "stale", "obsolete", indexed=False)
        connection.execute("UPDATE source_refs SET version='v2' WHERE key='stale'")
    original = migration.analyze

    seen = []

    def fail(text):
        seen.append(text)
        if len(seen) > 1:
            raise RuntimeError("interrupted migration")
        return original(text)

    monkeypatch.setattr(migration, "analyze", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        migration.initialize(database)
    assert table(database, "lexical_metadata") == []
    assert table(database, "lexical_postings") == []
    monkeypatch.setattr(migration, "analyze", original)
    migration.initialize(database)
    assert LexicalIndex(database).search("docs", "검색을", Principal())[0]["key"] == "current"
    assert LexicalIndex(database).search("docs", "obsolete", Principal()) == []
    monkeypatch.setattr(
        migration,
        "analyze",
        lambda _: pytest.fail("reopening a migrated database must not analyze documents"),
    )
    migration.initialize(database)
    assert table(database, "lexical_corpora")[0]["document_count"] == 2
