"""Credential scopes reduce authority before document or management dispatch."""

from galmuri.exposure.service.errors import ExposureError


def allowed(principal, scope, app=None):
    authorize = getattr(principal, "authorize", None)
    return not callable(authorize) or bool(authorize(scope, app))


def require(principal, scope, app=None):
    if not allowed(principal, scope, app):
        authenticated = getattr(principal, "is_authenticated", True)
        code = "forbidden" if authenticated else "unauthenticated"
        raise ExposureError(code, "The credential does not authorize this operation")
