"""Stable deployment identities for function references and explicit adapters."""

from types import BuiltinFunctionType, FunctionType


def callable_location(process):
    """Logical code location, independent of the project's checkout directory."""
    module = getattr(process, "__module__", type(process).__module__)
    qualified = getattr(process, "__qualname__", type(process).__qualname__)
    namespace, separator, remainder = module.partition(".")
    suffix = namespace.removeprefix("_workspace_")
    if (
        separator
        and namespace.startswith("_workspace_")
        and len(suffix) == 16
        and all(char in "0123456789abcdef" for char in suffix)
    ):
        module = remainder
    return f"{module}:{qualified}"


def callable_identity(process, identity=None, *, name="process"):
    if not callable(process):
        raise TypeError(f"{name} must be callable")
    if identity is None:
        identity = getattr(process, "identity", None)
    if identity is None and isinstance(process, (FunctionType, BuiltinFunctionType)):
        module = getattr(process, "__module__", None)
        qualified = getattr(process, "__qualname__", None)
        if module and qualified and "<lambda>" not in qualified:
            identity = callable_location(process)
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(f"Callable {name} requires an explicit {name} identity")
    return identity
