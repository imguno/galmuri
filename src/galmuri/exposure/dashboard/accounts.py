"""Account routes enforce caller authorization before trusted identity operations."""

from galmuri.exposure.service.errors import ExposureError

FIELDS = {
    "users.list": (set(), set()),
    "users.create": ({"username", "password"}, {"administrator", "root"}),
    "users.enabled": ({"user_id", "enabled"}, set()),
    "groups.list": (set(), set()),
    "groups.create": ({"name"}, set()),
    "groups.members": ({"group_id"}, set()),
    "groups.add": ({"group_id", "user_id"}, set()),
    "groups.remove": ({"group_id", "user_id"}, set()),
    "tokens.list": (set(), set()),
    "tokens.create": ({"name"}, {"scopes", "apps", "ttl"}),
    "tokens.revoke": ({"token_id"}, set()),
    "password.change": ({"password"}, set()),
}


def account_call(store, principal, operation, params):
    if operation not in FIELDS:
        raise ExposureError("unsupported", "Unknown account operation")
    if not isinstance(params, dict):
        raise ExposureError("invalid_request", "Parameters must be an object")
    required, optional = FIELDS[operation]
    if required - params.keys() or params.keys() - required - optional:
        raise ExposureError("invalid_request", "Missing or unknown parameters")
    if not getattr(principal, "is_authenticated", False):
        raise ExposureError("unauthenticated", "Login is required")
    directory = operation.startswith(("users.", "groups."))
    if not principal.authorize("manage" if directory else "read", "*" if directory else None):
        raise ExposureError("forbidden", "Account access is not permitted")
    if directory and not principal.administrator:
        raise ExposureError("forbidden", "Account administrator is required")
    if directory or operation in {"tokens.create", "password.change"}:
        if principal.credential_kind != "session":
            raise ExposureError("forbidden", "An account login session is required")
    for key, value in params.items():
        if key in {"enabled", "administrator", "root"}:
            valid = type(value) is bool
        elif key == "ttl":
            valid = type(value) is int and 60 <= value <= 31536000
        elif key in {"scopes", "apps"}:
            valid = (
                isinstance(value, list)
                and 1 <= len(value) <= 100
                and all(isinstance(item, str) and 0 < len(item) <= 256 for item in value)
            )
        else:
            valid = isinstance(value, str) and 0 < len(value) <= (
                1024 if key == "password" else 256
            )
        if not valid:
            raise ExposureError("invalid_request", f"Invalid {key}")
    if operation == "users.list":
        return store.list_users()
    if operation == "users.create":
        if params.get("root") and not getattr(principal, "root", False):
            raise ExposureError("forbidden", "An existing root account is required")
        return store.create_user(
            params["username"],
            params["password"],
            administrator=params.get("administrator", False),
            root=params.get("root", False),
        )
    if operation == "users.enabled":
        target = next(
            (user for user in store.list_users() if user["id"] == params["user_id"]), None
        )
        if target and target.get("root") and not getattr(principal, "root", False):
            raise ExposureError("forbidden", "An existing root account is required")
        return store.set_user_enabled(params["user_id"], params["enabled"])
    if operation == "groups.list":
        return store.list_groups()
    if operation == "groups.create":
        return store.create_group(params["name"])
    if operation == "groups.members":
        return store.members(params["group_id"])
    if operation == "groups.add":
        return store.add_member(params["group_id"], params["user_id"])
    if operation == "groups.remove":
        return store.remove_member(params["group_id"], params["user_id"])
    if operation == "tokens.list":
        return store.list_tokens(principal.subject)
    if operation == "tokens.create":
        return store.issue_token(
            principal.subject,
            params["name"],
            scopes=params.get("scopes", ["read"]),
            apps=params.get("apps", ["*"]),
            ttl=params.get("ttl", 2592000),
        )
    if operation == "tokens.revoke":
        return store.revoke_token(params["token_id"], user_id=principal.subject)
    return store.change_password(principal.subject, params["password"])
