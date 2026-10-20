"""Real MCP stdio host used by the integration test."""

from fakes import FakeRuntime

from galmuri.contracts.documents import Principal
from galmuri.exposure.mcp import McpAdapter
from galmuri.exposure.service import Service

if __name__ == "__main__":
    McpAdapter(Service(FakeRuntime()), principal=Principal("stdio-host")).run()
