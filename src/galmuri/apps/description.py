"""Describe resolved capabilities without exposing source credentials or document bodies."""

from duru import Provider, capabilities

from galmuri.ingestion.handler import IngestHandler
from galmuri.processing.pipeline import Pipeline


def configuration(app):
    source = app.source
    provider = getattr(source, "provider", None)
    if not isinstance(provider, Provider):
        provider = None
    implementation = type(provider if provider is not None else source)
    source_capabilities = sorted(capabilities(provider)) if provider is not None else ["read"]
    if app.writable and "write" not in source_capabilities:
        source_capabilities.append("write")
    discovery = getattr(source, "discovery_method", None)
    if discovery is None:
        discovery = "changes" if callable(getattr(source, "changes", None)) else "scan"
    selected = getattr(app.policy, "mode", "custom")
    if selected != "auto":
        discovery = "scan" if selected == "scan" else discovery
    result = {
        "source": {
            "implementation": f"{implementation.__module__}.{implementation.__qualname__}",
            "capabilities": source_capabilities,
            "discovery": discovery,
        },
        "workflow": {
            "implementation": type(app.policy).__qualname__,
            "interval": app.policy.interval,
        },
        "defaults_applied": list(app._resolution.defaults) if app._resolution else [],
    }
    if isinstance(app.handler, IngestHandler):
        result["ingestion"] = {
            "implementation": "builtin",
            "revision": app.handler.config.revision,
            "stages": ["read", "parse", "prepare", "publish"],
            "parser": {
                "identity": app.handler.parsing.identity,
                "revision": app.handler.parsing.revision,
            },
            "readers": "default" if "readers" in result["defaults_applied"] else "explicit",
            "writers": "default" if "writers" in result["defaults_applied"] else "explicit",
            "permissions": {
                "read": list(app.handler.config.readers),
                "write": list(app.handler.config.writers),
            },
        }
    elif isinstance(app.handler, Pipeline):
        steps = app.handler.steps
        result["ingestion"] = {
            "implementation": "pipeline",
            "revision": app.handler.fingerprint,
            "stages": ["read", *(step.name for step in steps), "publish"],
            "steps": [
                {
                    "name": step.name,
                    "accepts": step.accepts,
                    "returns": step.returns,
                    "identity": step.identity,
                    "revision": step.revision,
                }
                for step in steps
            ],
        }
    else:
        result["ingestion"] = {"implementation": "custom_handler"}
    retrieval = app.retrieval
    result["retrieval"] = (
        {
            "mode": retrieval.mode,
            "embedding": {
                "provider": retrieval.embedding.spec.provider,
                "model": retrieval.embedding.spec.model,
                "dimensions": retrieval.embedding.spec.dimensions,
                "revision": retrieval.embedding.spec.revision,
            },
            "chunker": retrieval.chunker.identity,
            "store": type(retrieval.store).__qualname__,
            "search": retrieval.search.describe(),
        }
        if retrieval is not None
        else {"mode": "lexical"}
    )
    return result


def operations(app):
    """Bound source operation parameters match the existing transport adapters."""
    modes = ["lexical", "vector", "hybrid"] if app.retrieval is not None else ["lexical"]
    text = {"type": "string", "minLength": 1}
    schemas = {
        "search": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": text,
                "mode": {"type": "string", "enum": modes},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 20},
            },
            "additionalProperties": False,
        },
        "read": {
            "type": "object",
            "required": ["document_key"],
            "properties": {"document_key": text},
            "additionalProperties": False,
        },
        "describe": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    if app.writable:
        schemas["write"] = {
            "type": "object",
            "required": ["document_key", "content", "expected_version"],
            "properties": {
                "document_key": text,
                "content": {"type": "string"},
                "expected_version": text,
            },
            "additionalProperties": False,
        }
    return schemas
