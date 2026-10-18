"""Prepare, persist, upload, then activate a fenced semantic generation."""

import json
import threading
import uuid
from itertools import islice

from galmuri.retrieval.indexing.artifacts import prepare as prepare_artifact
from galmuri.retrieval.indexing.claims import heartbeat, owned
from galmuri.retrieval.indexing.snapshots import cleanup, namespace
from galmuri.retrieval.models import VectorPoint
from galmuri.retrieval.validation import vector


def prepare(config, job):
    body = json.loads(job["body"])
    maximum = min(100_000, len(body["text"]) + 1)
    chunks = tuple(islice(iter(config.chunker.split(body["text"])), maximum + 1))
    if len(chunks) > maximum:
        raise ValueError("Chunker exceeded the per-document chunk limit")
    for chunk in chunks:
        if (
            not isinstance(chunk.start, int)
            or not isinstance(chunk.end, int)
            or not 0 <= chunk.start < chunk.end <= len(body["text"])
            or body["text"][chunk.start : chunk.end] != chunk.text
        ):
            raise ValueError("Chunk anchors must match the exact document text")
    values = []
    for start in range(0, len(chunks), config.batch_size):
        batch = chunks[start : start + config.batch_size]
        embeddings = tuple(
            islice(
                iter(config.embedding.embed_documents(tuple(chunk.text for chunk in batch))),
                len(batch) + 1,
            )
        )
        if len(embeddings) != len(batch):
            raise ValueError("Embedding provider returned an incorrect batch length")
        for chunk, embedding in zip(batch, embeddings, strict=True):
            values.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": chunk.text,
                    "start": chunk.start,
                    "end": chunk.end,
                    "vector": vector(embedding, config.embedding.spec.dimensions),
                }
            )
    return values


def execute(database, app, job, clock):
    config = app.retrieval
    stop = threading.Event()

    def renew():
        while not stop.wait(max(0.01, config.lease_seconds / 3)):
            if not heartbeat(database, job, clock, config.lease_seconds):
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    uploaded = False
    try:
        prepared = (
            json.loads(job["prepared"])
            if job["prepared"] is not None
            else prepare_artifact(database, config, job, clock, prepare)
        )
        with database.transaction() as connection:
            if not owned(connection, job, clock()):
                return
            connection.execute(
                "UPDATE semantic_builds SET stage='STORING',state='STORING',prepared=?,updated=? "
                "WHERE id=? AND token=?",
                (json.dumps(prepared), clock(), job["id"], job["token"]),
            )
        # A failed or crashed upload always reuses the persisted immutable IDs and vectors.
        uploaded = True
        config.store.ensure(namespace(job["fingerprint"]), config.embedding.spec.dimensions)
        points = tuple(VectorPoint(item["id"], tuple(item["vector"])) for item in prepared)
        for start in range(0, len(points), config.batch_size):
            config.store.upsert(
                namespace(job["fingerprint"]), points[start : start + config.batch_size]
            )
        with database.transaction() as connection:
            if owned(connection, job, clock()):
                connection.execute(
                    "UPDATE semantic_builds SET state='PUBLISHED',token=NULL,lease_until=NULL,"
                    "error=NULL,updated=? WHERE id=?",
                    (clock(), job["id"]),
                )
    except Exception as error:
        with database.transaction() as connection:
            if owned(connection, job, clock()):
                current = connection.execute(
                    "SELECT * FROM semantic_builds WHERE id=?", (job["id"],)
                ).fetchone()
                state = "FAILED" if current["attempts"] >= config.max_attempts else "RETRY_WAIT"
                connection.execute(
                    "UPDATE semantic_builds SET state=?,available=?,token=NULL,lease_until=NULL,"
                    "error=?,updated=? WHERE id=?",
                    (state, clock() + config.retry_delay, str(error), clock(), job["id"]),
                )
    finally:
        stop.set()
        thread.join()
        if uploaded:
            with database.transaction() as connection:
                current = connection.execute(
                    "SELECT * FROM semantic_builds WHERE id=?", (job["id"],)
                ).fetchone()
                # A late upsert may finish after a cleanup already ran. Requeue its exact IDs.
                if current["state"] == "SUPERSEDED":
                    cleanup(connection, current, clock())
                    if current["token"] == job["token"]:
                        connection.execute(
                            "UPDATE semantic_builds SET token=NULL,lease_until=NULL WHERE id=?",
                            (job["id"],),
                        )
