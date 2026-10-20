"""Observable ranking, Korean recall, authorization, and query-planner behavior."""

import unicodedata
from contextlib import closing, contextmanager

import pytest

from galmuri import Principal
from galmuri.documents.lexical import LexicalIndex
from galmuri.documents.lexical.analyzer import query_terms
from galmuri.documents.lexical.ranking import statement

from .helpers import publish


def keys(index, query, **kwargs):
    return [item["key"] for item in index.search("docs", query, Principal(), **kwargs)]


def test_bm25_rare_terms_and_length_normalization(database):
    with database.transaction() as connection:
        publish(connection, "rare-short", "quasar ordinary")
        publish(connection, "rare-long", "quasar ordinary " + "padding " * 100)
        for number in range(12):
            publish(connection, f"common-{number}", "ordinary " * 10)
    index = LexicalIndex(database)
    assert keys(index, "ordinary quasar")[0] == "rare-short"
    assert keys(index, "quasar") == ["rare-short", "rare-long"]
    result = index.search("docs", "quasar", Principal())
    assert all(item["score"] > 0 for item in result)


def test_bm25_values_rare_term_frequency_over_equally_common_words(database):
    with database.transaction() as connection:
        publish(connection, "rare-rich", "quasar quasar quasar ordinary")
        publish(connection, "common-rich", "quasar ordinary ordinary ordinary")
        for number in range(12):
            publish(connection, f"common-{number}", "ordinary")
    assert keys(LexicalIndex(database), "quasar ordinary") == ["rare-rich", "common-rich"]


@pytest.mark.parametrize(
    ("document", "query"),
    [
        ("검색 품질을 개선합니다", "검색품질"),
        ("검색품질 개선", "검색 품질"),
        ("검색", "검색을"),
        ("검색을", "검색"),
        ("한글", unicodedata.normalize("NFD", "한글")),
        ("ＡＢＣ Straße", "abc STRASSE"),
    ],
)
def test_unicode_korean_spacing_and_particles(database, document, query):
    with database.transaction() as connection:
        publish(connection, "match", document)
        publish(connection, "different", "unrelated")
    assert keys(LexicalIndex(database), query) == ["match"]


def test_terms_are_not_english_substrings_or_empty_wildcards(database):
    with database.transaction() as connection:
        publish(connection, "body", "concatenate ordinary")
    index = LexicalIndex(database)
    for query in ("cat", "", " \n\t", "...!?", "_", "___"):
        assert keys(index, query) == []
    with pytest.raises(ValueError, match="characters"):
        index.search("docs", "x" * 4097, Principal())
    with pytest.raises(ValueError, match="analyzed terms"):
        index.search("docs", " ".join(f"term{i}" for i in range(129)), Principal())
    for limit in (True, 0, 1001, 1.5):
        with pytest.raises(ValueError, match="limit"):
            index.search("docs", "ordinary", Principal(), limit)


def test_long_token_does_not_exceed_postgres_btree_entry_limit(database):
    token = "v" * 3500
    with database.transaction() as connection:
        publish(connection, "long-token", token)
    assert keys(LexicalIndex(database), token) == ["long-token"]


def test_compound_query_requires_half_its_full_hangul_bigram_set(database):
    with database.transaction() as connection:
        publish(connection, "refund-policy", "환불정책")
        publish(connection, "failure-cause", "실패원인")
        publish(connection, "compound", "환불실패")
        publish(connection, "particle", "문서")
    index = LexicalIndex(database)
    assert keys(index, "환불실패") == ["compound"]
    assert keys(index, "환불 실패") == ["compound"]
    assert keys(index, "문서를") == ["particle"]
    # Only one of three query bigrams exists; the absent two still count.
    assert keys(index, "문서쀍쀍") == []


def test_word_identifiers_and_mixed_queries_require_every_non_hangul_term(database):
    with database.transaction() as connection:
        publish(connection, "id", "user_id account 문서")
        publish(connection, "name", "user_name account 문서")
        publish(connection, "missing-word", "user_id 문서")
        publish(connection, "missing-hangul", "user_id account unrelated")
    index = LexicalIndex(database)
    assert set(keys(index, "user_id")) == {"id", "missing-word", "missing-hangul"}
    assert keys(index, "USER_ID account 문서를") == ["id"]
    assert keys(index, "user_id nonexistent") == []
    assert keys(index, "account user") == []
    assert keys(index, "user_id 문") == ["missing-word", "id"]


def test_app_scope_and_acl_pagination_reach_visible_lower_ranked_hits(database, monkeypatch):
    with database.transaction() as connection:
        for number in range(72):
            publish(connection, f"denied-{number:03}", "needle " * 20, readers=("group:hidden",))
        publish(connection, "visible", "needle " + "padding " * 40)
        publish(connection, "visible", "needle " * 30, app="elsewhere")
    index = LexicalIndex(database)
    rankings = []
    original = database.snapshot

    class Traced:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, *args):
            return self.connection.execute(*args)

        @contextmanager
        def stream(self, sql, parameters):
            rankings.append(sql)
            stream = getattr(self.connection, "stream", None)
            context = (
                stream(sql, parameters)
                if callable(stream)
                else closing(self.connection.execute(sql, parameters))
            )
            with context as cursor:
                yield cursor

    @contextmanager
    def traced_snapshot():
        with original() as connection:
            yield Traced(connection)

    monkeypatch.setattr(database, "snapshot", traced_snapshot)
    result = index.search("docs", "needle", Principal(), limit=1)
    assert [item["key"] for item in result] == ["visible"]
    assert result[0]["text"].startswith("needle padding")
    assert len(rankings) == 1


def test_source_intent_fence_even_if_obsolete_postings_remain(database):
    with database.transaction() as connection:
        publish(connection, "body", "obsolete")
        connection.execute("UPDATE source_refs SET version='v2' WHERE app='docs' AND key='body'")
    assert keys(LexicalIndex(database), "obsolete") == []


def test_acl_or_source_change_between_ranking_and_body_fetch_is_fenced(database, monkeypatch):
    with database.transaction() as connection:
        publish(connection, "acl", "needle")
        publish(connection, "version", "needle")
    index = LexicalIndex(database)
    original = index._fetch

    def change_then_fetch(app, selected, principal):
        with database.transaction() as connection:
            connection.execute("UPDATE documents SET readers='[]' WHERE key='acl'")
            connection.execute("UPDATE source_refs SET version='v2' WHERE key='version'")
        return original(app, selected, principal)

    monkeypatch.setattr(index, "_fetch", change_then_fetch)
    assert keys(index, "needle") == []


def test_sqlite_uses_term_index_and_fetches_only_selected_bodies(database, monkeypatch):
    if not hasattr(database, "path"):
        pytest.skip("SQLite query-planner assertion")
    with database.transaction() as connection:
        publish(connection, "selected", "unusual")
        for number in range(250):
            publish(connection, str(number), "unrelated " * 20)
    with database.connection() as connection:
        sql, parameters = statement(connection, "docs", query_terms("unusual"))
        plan = connection.execute("EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
    detail = "\n".join(row["detail"] for row in plan)
    assert "SEARCH p USING" in detail and "app=? AND term=?" in detail
    assert "SCAN d" not in detail
    seen = []
    original = database.connection

    @contextmanager
    def traced_connection():
        with original() as connection:
            connection.set_trace_callback(seen.append)
            yield connection

    monkeypatch.setattr(database, "connection", traced_connection)
    assert keys(LexicalIndex(database), "unusual", limit=1) == ["selected"]
    bodies = [sql for sql in seen if "SELECT d.*" in sql]
    assert len(bodies) == 1
    assert "d.key IN ('selected')" in bodies[0]
    assert not any("SELECT * FROM documents" in sql for sql in seen)
