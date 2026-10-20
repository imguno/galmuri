"""Resolved capability descriptions remain usable and do not reveal source secrets."""

import asyncio
import json

import pytest
from duru import ConditionalWritable, Provider

from galmuri import App, Pipeline, Principal, Step
from galmuri.exposure.mcp import McpAdapter
from galmuri.exposure.service import Service
from galmuri.runtime import Runtime


class PrivateProvider(Provider):
    root_uri = "opaque:private-root-location"
    identity = "account:private-scope"
    api_key = "secret-only-for-source-library"

    def stat(self, uri):
        raise AssertionError("Describing an app must not access its source")

    def open(self, uri, *, expected_revision=None):
        raise AssertionError("Describing an app must not read its source")


class WritableProvider(PrivateProvider, ConditionalWritable):
    def write(self, uri, content, *, expected_revision=None):
        raise AssertionError("Describing an app must not write its source")


@pytest.mark.parametrize("provider", [PrivateProvider, WritableProvider])
def test_describe_hides_secrets_and_matches_registered_mcp_operations(tmp_path, provider):
    pytest.importorskip("mcp")
    runtime = Runtime(tmp_path / "state.db", [App("knowledge", provider(), retrieval=None)])
    service = Service(runtime)
    description = runtime.describe("knowledge", Principal("outsider", administrator=True))
    raw = json.dumps(description)
    for value in (provider.root_uri, provider.identity, provider.api_key):
        assert value not in raw
    selected = description["configuration"]
    assert selected["ingestion"]["parser"]["identity"] == "galmuri.parsing:auto:v2"
    assert selected["ingestion"]["readers"] == "default"
    assert selected["ingestion"]["permissions"] == {"read": ["*"], "write": ["*"]}
    assert selected["retrieval"] == {"mode": "lexical"}
    assert description["operations"]["search"]["properties"]["mode"]["enum"] == ["lexical"]
    assert ("write" in description["operations"]) == (provider is WritableProvider)

    async def compare():
        adapter = McpAdapter(service)
        tools = {tool.name: tool for tool in await adapter.server.list_tools()}
        assert set(tools) == {"knowledge_" + name for name in description["operations"]}
        for name, schema in description["operations"].items():
            actual = tools["knowledge_" + name].inputSchema
            assert set(actual.get("properties", {})) == set(schema["properties"])
            assert set(actual.get("required", [])) == set(schema.get("required", []))

    asyncio.run(compare())


def test_describe_pipeline_contract_without_running_source_or_callback(tmp_path):
    def normalize(documents):
        raise AssertionError("Describing a pipeline must not execute it")

    process = Pipeline.default().then(Step("normalize", process=normalize, revision="2"))
    runtime = Runtime(
        tmp_path / "state.db",
        [App("knowledge", PrivateProvider(), process=process, retrieval=None)],
    )
    description = runtime.describe("knowledge", Principal("outsider"))
    selected = description["configuration"]["ingestion"]
    assert selected["implementation"] == "pipeline"
    assert selected["stages"] == ["read", "parse", "normalize", "prepare", "publish"]
    assert selected["steps"][1] == {
        "name": "normalize",
        "accepts": "documents",
        "returns": "documents",
        "identity": process.steps[1].identity,
        "revision": "2",
    }
    assert selected["revision"] == runtime.apps["knowledge"].process.fingerprint
    raw = json.dumps(description)
    for value in (PrivateProvider.api_key, PrivateProvider.root_uri, PrivateProvider.identity):
        assert value not in raw
