"""Transport-independent application commands and authorization boundary."""

import json
import logging
from typing import Any

from galmuri.contracts.documents import Principal
from galmuri.contracts.files import EffectUnknown, SourceConflict
from galmuri.contracts.requests import RequestConflict
from galmuri.exposure.service import documents
from galmuri.exposure.service.access import allowed, require
from galmuri.exposure.service.errors import ExposureError, failure
from galmuri.exposure.service.reconciliation import reconcile_call
from galmuri.exposure.service.worker import worker_call

logger = logging.getLogger(__name__)

MANAGEMENT = frozenset(
    {
        "status",
        "sync",
        "collect",
        "pause",
        "resume",
        "retry",
        "cancel",
        "reconcile",
        "reconcile_write",
        "worker.claim",
        "worker.complete",
        "worker.fail",
        "worker.heartbeat",
        "index_status",
        "reindex",
        "index_retry",
        "permission_inventory",
        "document_permissions",
    }
)
FIELDS = {
    "search": ({"app", "query"}, {"limit", "mode"}),
    "read": ({"app", "document_key"}, set()),
    "write": ({"app", "document_key", "content", "expected_version"}, set()),
    "describe": ({"app"}, set()),
    "capabilities": (set(), set()),
    "status": (set(), {"app"}),
    "sync": (set(), {"app"}),
    "collect": ({"app"}, {"force"}),
    "pause": ({"app"}, set()),
    "resume": ({"app"}, set()),
    "retry": ({"job_id"}, set()),
    "cancel": ({"job_id"}, set()),
    "reconcile": ({"job_id", "outcome"}, set()),
    "reconcile_write": ({"operation_id", "outcome"}, {"ref"}),
    "worker.claim": ({"worker_id"}, {"supported_apps"}),
    "worker.complete": ({"claim", "result"}, set()),
    "worker.fail": ({"claim", "error"}, {"kind"}),
    "worker.heartbeat": ({"claim"}, set()),
    "index_status": (set(), {"app"}),
    "reindex": (set(), {"app", "request_id"}),
    "index_retry": ({"job_id"}, set()),
    "documents": ({"app"}, {"query", "offset", "limit"}),
    "permission_inventory": ({"app"}, {"offset", "limit"}),
    "document_permissions": (
        {"app", "document_key", "readers", "writers", "expected_revision"},
        set(),
    ),
}


class Service:
    """All remote adapters use this boundary, never runtime storage internals."""

    def __init__(self, runtime: Any, identity=None):
        self.runtime = runtime
        self.identity = identity

    def capabilities(self, principal=None) -> dict:
        return {
            name: {
                "description": app.description,
                "operations": (
                    (
                        ["search", "read", "describe"]
                        if principal is None or allowed(principal, "read", name)
                        else []
                    )
                    + (
                        ["write"]
                        if app.writable and (principal is None or allowed(principal, "write", name))
                        else []
                    )
                ),
            }
            for name, app in self.runtime.apps.items()
            if principal is None
            or allowed(principal, "read", name)
            or allowed(principal, "write", name)
        }

    def call(self, operation: str, params: dict, principal: Principal) -> dict:
        try:
            result = self._dispatch(operation, params, principal)
            # An implementation contract violation must not fail in a protocol serializer.
            try:
                json.dumps(result, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                logger.error("Operation returned a non-JSON result: %s", operation)
                return failure("internal_error", "The operation returned an invalid result")
            return {"ok": True, "result": result}
        except ExposureError as exc:
            return failure(exc.code, str(exc))
        except PermissionError:
            return failure("forbidden", "This operation is not permitted")
        except (KeyError, FileNotFoundError):
            return failure("not_found", "The requested resource was not found")
        except SourceConflict:
            return failure("conflict", "The source version has changed; read before retrying")
        except RequestConflict:
            return failure("conflict", "Request identity was already used with different input")
        except EffectUnknown:
            return failure(
                "effect_unknown", "The operation requires reconciliation before retrying"
            )
        except (ValueError, TypeError):
            return failure("invalid_request", "The request violates the operation contract")
        except NotImplementedError:
            return failure("unsupported", "This operation is not supported")
        except Exception:
            logger.exception("Exposure operation failed: %s", operation)
            return failure("internal_error", "The operation could not be completed")

    def _dispatch(self, operation: str, params: dict, principal: Principal) -> Any:
        if not isinstance(operation, str) or operation not in FIELDS:
            raise ExposureError("unsupported", "Unknown operation")
        if not isinstance(params, dict):
            raise ExposureError("invalid_request", "Parameters must be an object")
        required, optional = FIELDS[operation]
        if required - params.keys() or params.keys() - required - optional:
            raise ExposureError("invalid_request", "Missing or unknown operation parameters")
        for key, value in params.items():
            if key in {"readers", "writers"}:
                if not isinstance(value, list):
                    raise ExposureError("invalid_request", f"{key} must be an array")
            elif key in {"offset", "expected_revision"}:
                if type(value) is not int or value < 0:
                    raise ExposureError("invalid_request", f"{key} must be a nonnegative integer")
            elif key in {"claim", "result", "ref", "supported_apps"}:
                if not isinstance(value, dict):
                    raise ExposureError("invalid_request", f"{key} must be an object")
            elif key == "limit":
                if type(value) is not int or not 1 <= value <= 1000:
                    raise ExposureError("invalid_request", "limit must be between 1 and 1000")
            elif key == "force":
                if type(value) is not bool:
                    raise ExposureError("invalid_request", "force must be a boolean")
            elif not isinstance(value, str) or (key not in {"content", "query"} and not value):
                raise ExposureError("invalid_request", f"{key} must be a nonempty string")
        scope = "manage" if operation in MANAGEMENT else "write" if operation == "write" else "read"
        target = params.get("app") or ("*" if operation in MANAGEMENT else None)
        require(principal, scope, target)
        if operation in MANAGEMENT and not principal.administrator:
            raise ExposureError("forbidden", "Management permission is required")
        if "mode" in params and params["mode"] not in {"lexical", "vector", "hybrid"}:
            raise ExposureError("invalid_request", "Unknown search mode")
        app = params.get("app")
        if app is not None and app not in self.runtime.apps:
            raise ExposureError("not_found", "The requested app was not found")
        if operation == "capabilities":
            return self.capabilities(principal)
        if operation in {"documents", "permission_inventory"}:
            return documents.listing(
                self.runtime,
                app,
                principal,
                query=params.get("query", ""),
                offset=params.get("offset", 0),
                limit=params.get("limit", 100),
                inventory=operation == "permission_inventory",
            )
        if operation == "document_permissions":
            return documents.permissions(self.runtime, self.identity, params)
        if operation in {"index_status", "reindex", "index_retry"}:
            indexing = getattr(self.runtime, "indexing", None)
            if indexing is None:
                raise ExposureError("unsupported", "Index management is not supported")
            if operation == "index_status":
                return indexing.status(app)
            if operation == "reindex":
                options = {"request_id": params["request_id"]} if "request_id" in params else {}
                return indexing.reindex(app, **options)
            return indexing.retry(params["job_id"])
        if operation.startswith("worker."):
            return worker_call(self.runtime, operation, params)
        if operation in {"reconcile", "reconcile_write"}:
            return reconcile_call(self.runtime, operation, params)
        if operation == "write" and not self.runtime.apps[app].writable:
            raise ExposureError("unsupported", "This source does not support writing")
        if operation == "search":
            options = {"mode": params["mode"]} if "mode" in params else {}
            return self.runtime.search(
                app, params["query"], principal, limit=params.get("limit", 20), **options
            )
        if operation == "read":
            return self.runtime.read(app, params["document_key"], principal)
        if operation == "write":
            return self.runtime.write(
                app,
                params["document_key"],
                params["content"],
                principal,
                expected_version=params["expected_version"],
            )
        if operation == "describe":
            return self.runtime.describe(app, principal)
        if operation in {"status", "sync"}:
            return getattr(self.runtime, operation)(app)
        if operation == "collect":
            return self.runtime.collect(app, force=params.get("force", False))
        if operation in {"pause", "resume"}:
            return getattr(self.runtime, operation)(app)
        return getattr(self.runtime, operation)(params["job_id"])
