"""Translate trusted worker receipts without trusting their publication baseline."""

import json

from galmuri.contracts.documents import Document
from galmuri.contracts.files import EffectUnknown
from galmuri.contracts.results import IngestResult
from galmuri.exposure.service.errors import ExposureError


def worker_call(runtime, operation, params):
    if operation == "worker.claim":
        supported = params.get("supported_apps")
        if supported is not None:
            if any(
                not isinstance(name, str)
                or not name
                or not isinstance(revision, str)
                or not revision
                for name, revision in supported.items()
            ):
                raise ExposureError("invalid_request", "Supported apps require names and revisions")
            return runtime.claim(params["worker_id"], supported_apps=supported)
        return runtime.claim(params["worker_id"])
    claim = params["claim"]
    if (
        not isinstance(claim.get("id"), str)
        or not claim["id"]
        or not isinstance(claim.get("token"), str)
        or not claim["token"]
    ):
        raise ExposureError("invalid_request", "Claim identity and lease token are required")
    # Runtime reloads authoritative lease metadata. Caller-supplied revisions and ACL
    # generations are not accepted as authorization or publication evidence here.
    if operation == "worker.heartbeat":
        return runtime.heartbeat(claim)
    if operation == "worker.fail":
        kind = params.get("kind", "failure")
        if kind not in {"failure", "effect_unknown"}:
            raise ExposureError("invalid_request", "Unknown failure kind")
        error_type = EffectUnknown if kind == "effect_unknown" else RuntimeError
        return runtime.fail(claim, error_type(params["error"][:4096]))
    result = params["result"]
    if result.keys() - {"documents", "messages"} or not isinstance(result.get("documents"), list):
        raise ExposureError("invalid_request", "Invalid processing result")
    messages = result.get("messages", [])
    if not isinstance(messages, list) or any(not isinstance(item, str) for item in messages):
        raise ExposureError("invalid_request", "Result messages must be strings")
    documents = []
    for item in result["documents"]:
        if (
            not isinstance(item, dict)
            or item.keys() - {"key", "text", "metadata", "readers", "writers"}
            or not isinstance(item.get("key"), str)
            or not item["key"]
            or not isinstance(item.get("text"), str)
            or not isinstance(item.get("metadata", {}), dict)
        ):
            raise ExposureError("invalid_request", "Invalid document projection")
        try:
            json.dumps(item.get("metadata", {}), allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise ExposureError("invalid_request", "Metadata must contain JSON values") from None
        for field in ("readers", "writers"):
            grants = item.get(field, [])
            if not isinstance(grants, list) or any(
                not isinstance(grant, str) or not grant for grant in grants
            ):
                raise ExposureError("invalid_request", "Document grants must be lists of strings")
        documents.append(
            Document(
                key=item["key"],
                text=item["text"],
                metadata=item.get("metadata", {}),
                readers=tuple(item.get("readers", [])),
                writers=tuple(item.get("writers", [])),
            )
        )
    return runtime.complete(claim, IngestResult(tuple(documents), tuple(messages)))
