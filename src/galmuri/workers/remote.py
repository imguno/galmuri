"""Remote workers execute app code locally and exchange only serialized contracts."""

import json
import threading
from collections.abc import Mapping
from dataclasses import asdict
from urllib.request import HTTPRedirectHandler, Request, build_opener

from galmuri.apps.definition import App
from galmuri.contracts.files import EffectUnknown, FileRef
from galmuri.contracts.results import IngestResult


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class HttpWorker:
    def __init__(self, endpoint: str, token: str, apps: Mapping[str, App], worker_id: str):
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("Worker coordinator must use HTTP or HTTPS")
        self.endpoint = endpoint.rstrip("/") + "/api/call"
        self.token = token
        self.apps = apps
        self.worker_id = worker_id

    def call(self, operation: str, params: dict):
        body = json.dumps({"operation": operation, "params": params}).encode()
        request = Request(
            self.endpoint,
            body,
            {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            envelope = json.load(response)
        if not envelope.get("ok"):
            raise RuntimeError(
                envelope.get("error", {}).get("message", "Coordinator rejected call")
            )
        return envelope.get("result")

    def run_once(self) -> bool:
        claim = self.call(
            "worker.claim",
            {
                "worker_id": self.worker_id,
                "supported_apps": {name: app.revision for name, app in self.apps.items()},
            },
        )
        if claim is None:
            return False
        if claim.get("skip"):
            return True
        stop = threading.Event()
        app = self.apps.get(claim["app"])
        if app is None:
            self.call("worker.fail", {"claim": claim, "error": "Worker has no matching app"})
            return True
        if app.revision != claim["revision"]:
            self.call("worker.fail", {"claim": claim, "error": "Worker app revision mismatch"})
            return True

        def renew() -> None:
            while not stop.wait(max(0.05, app.policy.lease_seconds / 3)):
                try:
                    if not self.call("worker.heartbeat", {"claim": claim}):
                        return
                except (OSError, RuntimeError):
                    return

        heartbeat = threading.Thread(target=renew, name="lease-renewal", daemon=True)
        heartbeat.start()
        try:
            if claim["deleted"]:
                result = IngestResult(())
            else:
                metadata = claim["metadata"]
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                ref = FileRef(claim["source_key"], claim["version"], metadata)
                result = app.policy.execute(app.source, ref, app.handler)
            self.call("worker.complete", {"claim": claim, "result": asdict(result)})
        except Exception as error:
            self.call(
                "worker.fail",
                {
                    "claim": claim,
                    "error": str(error),
                    "kind": "effect_unknown" if isinstance(error, EffectUnknown) else "failure",
                },
            )
        finally:
            stop.set()
            heartbeat.join(timeout=2)
        return True
