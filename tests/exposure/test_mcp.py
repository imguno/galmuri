import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from galmuri.contracts.documents import Principal
from galmuri.exposure.mcp import McpAdapter
from galmuri.exposure.service import Service

from .fakes import FakeRuntime


def test_official_mcp_tools_have_no_identity_arguments_and_hide_unsupported_write():
    pytest.importorskip("mcp")
    runtime = FakeRuntime()
    caller = Principal("configured-host")
    adapter = McpAdapter(Service(runtime), principal=caller)

    async def scenario():
        tools = {tool.name: tool for tool in await adapter.server.list_tools()}
        assert "readonly_write" not in tools
        assert "editable_write" in tools
        assert set(tools["readonly_search"].inputSchema["properties"]) == {"query", "limit", "mode"}
        for name in ("readonly_search", "readonly_read", "readonly_describe"):
            annotations = tools[name].annotations
            assert annotations.readOnlyHint is True
            assert annotations.destructiveHint is False
            assert annotations.idempotentHint is True
            assert annotations.openWorldHint is False
        write = tools["editable_write"].annotations
        assert write.readOnlyHint is False
        assert write.destructiveHint is True
        assert write.idempotentHint is False
        assert write.openWorldHint is True
        result = await adapter.server.call_tool("readonly_read", {"document_key": "guide"})
        assert result
        assert runtime.last_principal is caller

    asyncio.run(scenario())


def test_official_mcp_stdio_client_roundtrip():
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).with_name("stdio_host.py"))],
            env=environment,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert "readonly_search" in {tool.name for tool in tools.tools}
            result = await session.call_tool("readonly_read", {"document_key": "guide"})
            assert not result.isError
            data = json.loads(result.content[0].text)
            assert data["ok"] is True
            assert data["result"]["key"] == "guide"
            assert result.structuredContent == data
            for name, arguments, expected_code in (
                ("readonly_read", {"document_key": "private"}, "forbidden"),
                ("readonly_search", {"query": "guide", "limit": 0}, "invalid_request"),
                ("readonly_read", {"document_key": "explode"}, "internal_error"),
            ):
                failed = await session.call_tool(name, arguments)
                envelope = json.loads(failed.content[0].text)
                assert failed.isError is True
                assert envelope["ok"] is False
                assert envelope["error"]["code"] == expected_code
                assert failed.structuredContent == envelope
                assert "secret database credentials" not in failed.content[0].text

    asyncio.run(scenario())
