"""Real separate processes share intent, claim and publication contracts."""

import os
import time

from galmuri import Principal
from tools.multi_instance_acceptance.fixture import publish, runtime


def initial(config, count=2):
    publish(
        config["source"],
        {
            f"doc{index}": {"version": "1", "text": f"source version one document {index}"}
            for index in range(count)
        },
    )


def simultaneous(processes):
    ready = [process.wait_file("ready.json") for process in processes]
    assert len({item["pid"] for item in ready}) == len(processes)
    assert all(item["pid"] != os.getpid() for item in ready)
    for process in processes:
        process.signal("start")


def test_simultaneous_startup_collect_deduplicates_durable_intents(scenario):
    config, start = scenario
    initial(config)
    processes = [start("collect") for _ in range(3)]
    simultaneous(processes)
    results = [process.wait_file("result.json") for process in processes]
    for process in processes:
        process.finish()
    instance = runtime(config)
    jobs = instance.status()["jobs"]
    assert len(jobs) == 2
    assert {(job["source_key"], job["version"]) for job in jobs} == {("doc0", "1"), ("doc1", "1")}
    assert sum(result["enqueued"] for result in results) == 2


def test_simultaneous_ingesters_and_indexers_have_disjoint_claims(scenario):
    config, start = scenario
    initial(config)
    instance = runtime(config)
    instance.collect("sample", force=True)
    ingesters = [start("ingest") for _ in range(2)]
    simultaneous(ingesters)
    claims = [process.wait_file("claim.json") for process in ingesters]
    assert len({job["id"] for job in claims}) == 2
    assert len({job["source_key"] for job in claims}) == 2
    for process in ingesters:
        process.signal("release")
    assert all(process.wait_file("result.json")["completed"] for process in ingesters)
    for process in ingesters:
        process.finish()
    indexers = [start("index") for _ in range(2)]
    simultaneous(indexers)
    builds = [process.wait_file("claim.json") for process in indexers]
    assert len({job["id"] for job in builds}) == 2
    assert len({job["key"] for job in builds}) == 2
    for process in indexers:
        process.signal("release")
    for process in indexers:
        process.wait_file("result.json")
        process.finish()
    restarted = runtime(config)
    matches = restarted.search("sample", "semantic fixture query", Principal())
    assert {match["key"] for match in matches} == {"doc0", "doc1"}
    assert {match["build"] for match in matches} == {build["id"] for build in builds}


def test_terminated_worker_enters_reconciliation_without_automatic_replay(scenario):
    config, start = scenario
    initial(config, count=1)
    instance = runtime(config)
    instance.collect("sample", force=True)
    abandoned = start("abandon", lease_seconds=0.4)
    simultaneous([abandoned])
    job = abandoned.wait_file("claim.json")
    abandoned.stop()
    deadline = time.monotonic() + 5
    while instance.database.now() <= job["lease_until"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert instance.claim("replacement") is None
    status = instance.status()["jobs"]
    assert status[0]["state"] == "RECONCILING"
    assert instance.search("sample", "query", Principal()) == []
    instance.reconcile(job["id"], "retry_safe")
    assert instance.work_once("confirmed-safe-replacement")
    instance.drain()
    assert instance.search("sample", "query", Principal())[0]["version"] == "1"


def test_new_source_intent_fences_old_process_publication(scenario):
    config, start = scenario
    initial(config, count=1)
    instance = runtime(config)
    instance.collect("sample", force=True)
    old = start("ingest")
    simultaneous([old])
    old_job = old.wait_file("claim.json")
    publish(config["source"], {"doc0": {"version": "2", "text": "only current generation"}})
    instance.collect("sample", force=True)
    old.signal("release")
    assert old.wait_file("result.json")["completed"] is False
    old.finish()
    instance.drain()
    assert (
        next(row for row in instance.status()["jobs"] if row["id"] == old_job["id"])["state"]
        == "SUPERSEDED"
    )
    assert instance.read("sample", "doc0", Principal())["text"] == "only current generation"
    assert instance.search("sample", "query", Principal())[0]["version"] == "2"


def test_late_vector_upload_from_old_process_is_never_published_and_is_cleaned(scenario):
    config, start = scenario
    initial(config, count=1)
    instance = runtime(config)
    instance.collect("sample", force=True)
    assert instance.work_once("body")
    old = start("index_upload")
    simultaneous([old])
    upload = old.wait_file("claim.json")
    old_build = instance.indexing.status()["jobs"][0]["id"]
    publish(config["source"], {"doc0": {"version": "2", "text": "current semantic generation"}})
    instance.collect("sample", force=True)
    assert instance.work_once("new-body")
    assert instance.search("sample", "query", Principal()) == []
    old.signal("release")
    assert old.wait_file("result.json")["worked"]
    old.finish()
    instance.drain()
    result = instance.search("sample", "query", Principal())[0]
    assert result["version"] == "2"
    assert result["build"] != old_build
    cleanup_status = instance.indexing.status()
    with instance.database.connection() as connection:
        for identifier in upload["ids"]:
            assert (
                connection.execute(
                    "SELECT 1 FROM vector_points WHERE id=?", (identifier,)
                ).fetchone()
                is None
            ), cleanup_status


def test_parallel_same_id_reindex_requests_replay_the_same_generation_set(scenario):
    config, start = scenario
    initial(config)
    instance = runtime(config)
    instance.sync()
    original = {match["build"] for match in instance.search("sample", "query", Principal())}
    config["request_id"] = "reindex-request-from-retried-client"
    clients = [start("reindex") for _ in range(3)]
    simultaneous(clients)
    results = [client.wait_file("result.json") for client in clients]
    for client in clients:
        client.finish()
    assert results[0] == results[1] == results[2]
    assert results[0]["scheduled"] == 2
    assert not original.intersection(results[0]["jobs"])
    with instance.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_requests").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM semantic_builds").fetchone()[0] == 4
    instance.drain()
    assert {match["build"] for match in instance.search("sample", "query", Principal())} == set(
        results[0]["jobs"]
    )
    later_retry = start("reindex")
    simultaneous([later_retry])
    assert later_retry.wait_file("result.json") == results[0]
    later_retry.finish()
    config["request_id"] = "deliberately-new-reindex-request"
    next_request = start("reindex")
    simultaneous([next_request])
    next_result = next_request.wait_file("result.json")
    next_request.finish()
    assert next_result["scheduled"] == 2
    assert not set(next_result["jobs"]).intersection(results[0]["jobs"])
    with instance.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM semantic_requests").fetchone()[0] == 2
    instance.drain()
    assert {match["build"] for match in instance.search("sample", "query", Principal())} == set(
        next_result["jobs"]
    )
