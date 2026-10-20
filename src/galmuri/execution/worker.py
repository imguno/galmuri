"""A local worker uses the same claims as remote workers."""

import json
import threading

from galmuri.collection.policies import SyncPolicy
from galmuri.contracts.files import FileRef
from galmuri.contracts.results import IngestResult


def work_once(runtime, worker_id, supported_apps=None):
    claim = runtime.claim(worker_id, supported_apps)
    if claim is None:
        return False
    if claim.get("skip"):
        return True
    app = runtime.apps[claim["app"]]
    stop = threading.Event()

    def renew():
        interval = max(0.01, app.policy.lease_seconds / 3)
        while not stop.wait(interval):
            if not runtime.heartbeat(claim):
                return

    renewal = threading.Thread(target=renew, daemon=True)
    renewal.start()
    try:
        ref = FileRef(claim["source_key"], claim["version"], json.loads(claim["metadata"]))
        ingestion = getattr(runtime, "ingestion", None)
        if claim["deleted"]:
            result = IngestResult(())
        elif (
            ingestion is not None
            and getattr(app.handler, "durable_ingestion", False)
            and type(app.policy) is SyncPolicy
        ):
            result = ingestion.run(claim, app)
        else:
            # Custom workflow execution and arbitrary handlers retain their effect contract.
            result = app.policy.execute(app.source, ref, app.handler)
        runtime.complete(claim, result)
    except Exception as error:
        runtime.fail(claim, error)
    finally:
        stop.set()
        renewal.join()
        release = getattr(getattr(runtime, "ingestion", None), "release_completed", None)
        if callable(release):
            release()
    return True
