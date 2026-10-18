"""Actual generated project, local resource library, durable runtime and MCP SDK.

This verifies the transport deterministically. An LLM's tool selection and answer
grounding require a separate live-client run; fixed calls here are not LLM evidence.
"""

import asyncio
from pathlib import Path

import pytest

from .support.project import GeneratedProject, successful_tool, tool


def test_generated_project_mcp_acl_write_reindex_delete_and_restart(tmp_path: Path):
    pytest.importorskip("mcp")
    project = GeneratedProject.create(tmp_path / "knowledge")
    fixture = project.fixtures / "acceptance.md"
    fixture.write_text("# Acceptance\n\nThe cobalt orchid launch code is NOVA-731.\n", "utf-8")
    initial = project.command("sync")
    assert initial["processed"] == 3

    async def scenario():
        async with project.host("public") as public:
            advertised = {entry.name: entry for entry in (await public.list_tools()).tools}
            assert set(advertised) == {
                "sample_describe",
                "sample_search",
                "sample_read",
                "sample_write",
            }
            assert "principal" not in advertised["sample_read"].inputSchema["properties"]
            invalid = await tool(public, "search", query="guide", limit=0)
            assert invalid["error"]["code"] == "invalid_request"
            description = await successful_tool(public, "describe")
            assert description["search"]["method"] == "lexical"
            assert description["search"]["visible_documents"] == 2
            assert description["guides"]
            assert await successful_tool(public, "search", query="Deployment operations") == []
            matches = await successful_tool(public, "search", query="cobalt orchid")
            assert len(matches) == 1
            original = await successful_tool(public, "read", document_key=matches[0]["key"])
            assert "NOVA-731" in original["text"]
            denied = await tool(
                public,
                "write",
                document_key=original["key"],
                content="unauthorized",
                expected_version=original["version"],
            )
            assert denied["error"]["code"] == "forbidden"
            assert fixture.read_text("utf-8").endswith("NOVA-731.\n")

        async with project.host("dev") as developer:
            description = await successful_tool(developer, "describe")
            assert description["search"]["visible_documents"] == 3
            private = await successful_tool(developer, "search", query="Deployment operations")
            assert len(private) == 1
            private_key = private[0]["key"]
            private_read = await successful_tool(developer, "read", document_key=private_key)
            assert "restricted to the dev group" in private_read["text"]
            write = await successful_tool(
                developer,
                "write",
                document_key=original["key"],
                content="# Acceptance\n\nThe amber comet launch code is AURORA-942.\n",
                expected_version=original["version"],
            )
            assert write["state"] == "SUCCEEDED"
            assert write["version"] != original["version"]

        async with project.host("admin") as administrator:
            assert (
                await successful_tool(administrator, "search", query="Deployment operations") == []
            )
            denied = await tool(administrator, "read", document_key=private_key)
            assert denied["error"]["code"] == "forbidden"

        # A distinct CLI process reopens durable state and finishes queued reindexing.
        project.command("sync")
        async with project.host("public") as restarted:
            denied = await tool(restarted, "read", document_key=private_key)
            assert denied["error"]["code"] == "forbidden"
            assert await successful_tool(restarted, "search", query="cobalt orchid") == []
            current = await successful_tool(restarted, "search", query="amber comet")
            assert len(current) == 1
            assert current[0]["version"] == write["version"]
            assert "AURORA-942" in current[0]["text"]
            read = await successful_tool(restarted, "read", document_key=original["key"])
            assert read == {key: value for key, value in current[0].items() if key != "score"}

        async with project.host("dev") as developer:
            stale = await tool(
                developer,
                "write",
                document_key=original["key"],
                content="stale overwrite",
                expected_version=original["version"],
            )
            assert stale["error"]["code"] == "conflict"
        assert "AURORA-942" in fixture.read_text("utf-8")

        fixture.unlink()
        deletion = project.command("sync")
        assert deletion["processed"] == 1
        async with project.host("public") as restarted:
            assert await successful_tool(restarted, "search", query="amber comet") == []
            deleted = await tool(restarted, "read", document_key=original["key"])
            assert deleted["error"]["code"] == "forbidden"
            description = await successful_tool(restarted, "describe")
            assert description["search"]["visible_documents"] == 1
            welcome = await successful_tool(restarted, "search", query="source apps")
            assert len(welcome) == 1

    asyncio.run(scenario())


def test_generated_serve_ingests_existing_and_new_files_without_manual_sync(tmp_path: Path):
    pytest.importorskip("mcp")
    project = GeneratedProject.create(tmp_path / "background")
    policy = project.root / "apps" / "sample" / "policies" / "collection.py"
    # Schedule remains app-owned; shorten only the generated app's interval for this test.
    policy.write_text(policy.read_text("utf-8").replace("interval=60", "interval=0.1"), "utf-8")

    async def scenario():
        async with project.host("public") as session:
            async with asyncio.timeout(20):
                while True:
                    description = await successful_tool(session, "describe")
                    if description["search"]["visible_documents"] == 1:
                        break
                    await asyncio.sleep(0.05)
                welcome = await successful_tool(session, "search", query="source apps")
                assert len(welcome) == 1
                (project.fixtures / "arrival.md").write_text(
                    "# Arrival\n\nThe scheduled silver willow code is SKY-583.\n", "utf-8"
                )
                while True:
                    arrivals = await successful_tool(session, "search", query="silver willow")
                    if arrivals:
                        break
                    await asyncio.sleep(0.05)
                assert len(arrivals) == 1
                document = await successful_tool(session, "read", document_key=arrivals[0]["key"])
                assert "SKY-583" in document["text"]

    asyncio.run(scenario())
