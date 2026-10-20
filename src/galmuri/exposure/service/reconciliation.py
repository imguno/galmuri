"""Validate operator reconciliation receipts at the service boundary."""

import json

from galmuri.contracts.files import FileRef
from galmuri.exposure.service.errors import ExposureError


def reconcile_call(runtime, operation, params):
    if operation == "reconcile":
        if params["outcome"] not in {"retry_safe", "failed", "cancelled"}:
            raise ExposureError("invalid_request", "Unknown job reconciliation outcome")
        return runtime.reconcile(params["job_id"], params["outcome"])
    outcome = params["outcome"]
    if outcome not in {"applied", "not_applied", "failed"}:
        raise ExposureError("invalid_request", "Unknown write reconciliation outcome")
    value = params.get("ref")
    if outcome != "applied":
        if value is not None:
            raise ExposureError("invalid_request", "Only applied writes accept a source receipt")
        return runtime.reconcile_write(params["operation_id"], outcome)
    if (
        not isinstance(value, dict)
        or value.keys() - {"key", "version", "metadata"}
        or not isinstance(value.get("key"), str)
        or not value["key"]
        or not isinstance(value.get("version"), str)
        or not value["version"]
        or not isinstance(value.get("metadata", {}), dict)
    ):
        raise ExposureError("invalid_request", "Applied writes require an exact source receipt")
    try:
        json.dumps(value.get("metadata", {}), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ExposureError(
            "invalid_request", "Receipt metadata must contain JSON values"
        ) from None
    ref = FileRef(value["key"], value["version"], value.get("metadata", {}))
    return runtime.reconcile_write(params["operation_id"], outcome, ref)
