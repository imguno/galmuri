"""Current document browsing and explicit ACL management; no source-provider IO."""

from galmuri.exposure.service.access import allowed
from galmuri.exposure.service.errors import ExposureError


def listing(runtime, app_name, principal, *, query="", offset=0, limit=100, inventory=False):
    result = runtime.queries.list_documents(
        app_name, principal, query=query, offset=offset, limit=limit, inventory=inventory
    )
    can_write = runtime.apps[app_name].writable and allowed(principal, "write", app_name)
    for item in result["items"]:
        item["can_write"] = bool(item["can_write"] and can_write)
    return result


def _grants(values, identity):
    if not isinstance(values, list) or len(values) > 1000:
        raise ExposureError("invalid_request", "Grants must be an array of at most 1000 entries")
    users = {user["id"] for user in identity.list_users()} if identity is not None else set()
    groups = {group["id"] for group in identity.list_groups()} if identity is not None else set()
    for value in values:
        if not isinstance(value, str):
            raise ExposureError("invalid_request", "Invalid document grant")
        if value == "*":
            continue
        kind, separator, identifier = value.partition(":")
        if (
            not separator
            or not identifier
            or (
                kind == "user"
                and identifier not in users
                or kind == "group"
                and identifier not in groups
                or kind not in {"user", "group"}
            )
        ):
            raise ExposureError("invalid_request", "Select an existing account or group")
    return tuple(dict.fromkeys(values))


def permissions(runtime, identity, params):
    readers = _grants(params["readers"], identity)
    writers = _grants(params["writers"], identity)
    try:
        revision = runtime.documents.set_permissions(
            params["app"],
            params["document_key"],
            readers,
            writers,
            expected_revision=params["expected_revision"],
        )
    except ValueError:
        raise ExposureError(
            "conflict", "Document permissions changed; refresh before retrying"
        ) from None
    return {
        "key": params["document_key"],
        "readers": list(readers),
        "writers": list(writers),
        "permissions_revision": revision,
    }
