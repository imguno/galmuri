"""A real Python process controlled by durable test barriers, never mocked claims."""

import argparse
import json
import os
import time
from pathlib import Path

from galmuri import FileRef
from galmuri.retrieval.indexing.claims import claim as claim_index
from galmuri.retrieval.indexing.execution import execute as execute_index
from galmuri.retrieval.indexing.reconciliation import reconcile
from tools.multi_instance_acceptance.fixture import publish, runtime


def wait(path):
    deadline = time.monotonic() + 30
    while not Path(path).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Process acceptance barrier did not release")
        time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("configuration")
    parser.add_argument("directory")
    parser.add_argument(
        "action", choices=("collect", "ingest", "index", "index_upload", "abandon", "reindex")
    )
    args = parser.parse_args()
    control = Path(args.directory)
    config = json.loads(Path(args.configuration).read_text(encoding="utf-8"))
    publish(control / "ready.json", {"ready": True, "pid": os.getpid()})
    wait(control / "start")
    instance = runtime(config)
    if args.action == "collect":
        publish(control / "result.json", instance.collect("sample", force=True))
        return
    if args.action == "reindex":
        result = instance.indexing.reindex("sample", request_id=config["request_id"])
        publish(control / "result.json", result)
        return
    if args.action == "index_upload":
        store = instance.apps["sample"].retrieval.store
        original = store.upsert

        def delayed_upload(namespace, points):
            publish(control / "claim.json", {"ids": [point.id for point in points]})
            wait(control / "release")
            original(namespace, points)

        store.upsert = delayed_upload
        worked = instance.indexing.work_once(control.name)
        publish(control / "result.json", {"worked": worked})
        return
    if args.action == "index":
        reconcile(instance.database, instance.apps, instance.indexing.clock)
        job = claim_index(instance.database, instance.apps, instance.indexing.clock, control.name)
        publish(control / "claim.json", job)
        wait(control / "release")
        if job:
            execute_index(instance.database, instance.apps["sample"], job, instance.indexing.clock)
        publish(control / "result.json", {"claimed": job["id"] if job else None})
        return
    job = instance.claim(control.name)
    if job is None:
        publish(control / "claim.json", None)
        publish(control / "result.json", {"completed": False})
        return
    # Prepare the old version before the parent changes the source or kills us.
    app = instance.apps["sample"]
    ref = FileRef(job["source_key"], job["version"], json.loads(job["metadata"]))
    prepared = app.policy.execute(app.source, ref, app.handler)
    publish(control / "claim.json", job)
    wait(control / "release")
    completed = instance.complete(job, prepared)
    publish(control / "result.json", {"completed": completed, "job": job["id"]})


if __name__ == "__main__":
    main()
