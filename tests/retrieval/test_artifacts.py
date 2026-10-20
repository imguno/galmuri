"""An external store is replaceable without re-running compatible model inference."""

import json
from dataclasses import replace

from galmuri.retrieval import CharacterChunker, EmbeddingSpec, RetrievalConfig
from galmuri.runtime import Runtime
from tests.retrieval.test_projection import DEV, Store, fixture


def point_ids(runtime):
    with runtime.database.connection() as connection:
        return [
            set(item["id"] for item in json.loads(row[0]))
            for row in connection.execute(
                "SELECT prepared FROM semantic_builds WHERE prepared IS NOT NULL "
                "ORDER BY created,id"
            )
        ]


def test_reindex_reuses_embeddings_but_allocates_new_generation_ids(tmp_path):
    runtime, _, embedding, _ = fixture(tmp_path)
    runtime.sync()
    first = point_ids(runtime)[0]
    runtime.indexing.reindex()
    runtime.drain()
    assert embedding.calls == 1
    assert len(point_ids(runtime)) == 2
    assert first.isdisjoint(point_ids(runtime)[1])
    assert runtime.search("sample", "q", DEV)


def test_storage_switch_reuses_embeddings_with_new_point_ids(tmp_path):
    runtime, _, embedding, store = fixture(tmp_path)
    runtime.sync()
    first = point_ids(runtime)[0]
    replacement = Store()
    replacement.identity = "replacement-store"
    config = RetrievalConfig(embedding, replacement)
    updated = Runtime(
        runtime.database.path,
        [replace(runtime.apps["sample"], retrieval=config)],
        activate=True,
        cleanup_stores=(store,),
    )
    updated.drain()
    assert embedding.calls == 1
    assert first.isdisjoint(set(replacement.points))
    assert updated.search("sample", "q", DEV)


def test_embedding_and_chunker_identity_changes_invalidate_artifacts(tmp_path):
    runtime, _, embedding, store = fixture(tmp_path)
    runtime.sync()
    embedding.spec = EmbeddingSpec("test-only", "deterministic", 2, "2")
    config = replace(runtime.apps["sample"].retrieval, embedding=embedding)
    updated = Runtime(
        runtime.database.path, [replace(runtime.apps["sample"], retrieval=config)], activate=True
    )
    updated.drain()
    assert embedding.calls == 2
    config = replace(config, chunker=CharacterChunker(size=5, overlap=0))
    updated = Runtime(
        runtime.database.path, [replace(updated.apps["sample"], retrieval=config)], activate=True
    )
    updated.drain()
    assert embedding.calls == 3


def test_source_changed_while_embedding_cannot_accept_reusable_artifact(tmp_path):
    runtime, source, embedding, _ = fixture(tmp_path)
    runtime.collect("sample")
    runtime.work_once()
    original = embedding.embed_documents

    def changed(texts):
        source.version = "2"
        runtime.collect("sample", force=True)
        return original(texts)

    embedding.embed_documents = changed
    runtime.indexing.work_once("old")
    with runtime.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_artifacts").fetchone()[0] == 0
    assert runtime.search("sample", "query", DEV) == []
