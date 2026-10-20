"""Generate and operate a project exclusively through its public CLI and MCP."""

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


@dataclass(frozen=True)
class GeneratedProject:
    root: Path
    environment: dict[str, str]

    @classmethod
    def create(cls, root: Path):
        environment = dict(os.environ)
        source = Path(__file__).resolve().parents[3] / "src"
        # Subprocesses must run this checkout, including on an uninstalled test host.
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(source), environment.get("PYTHONPATH", "")) if part
        )
        subprocess.run(
            [sys.executable, "-m", "galmuri", "new", str(root), "--lexical"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        settings = root / "config" / "settings.py"
        with settings.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n# Acceptance hosts select their identity outside tool arguments.\n"
                "import os\n"
                'if os.environ.get("ACCEPTANCE_HOST") == "public":\n'
                '    LOCAL_PRINCIPAL = Principal("public-reader")\n'
                'elif os.environ.get("ACCEPTANCE_HOST") == "dev":\n'
                '    LOCAL_PRINCIPAL = Principal("dev-reader", frozenset({"dev"}))\n'
                'elif os.environ.get("ACCEPTANCE_HOST") == "admin":\n'
                '    LOCAL_PRINCIPAL = Principal("operator", administrator=True)\n'
            )
        return cls(root, environment)

    @property
    def fixtures(self):
        return self.root / "apps" / "sample" / "fixtures"

    def command(self, *arguments):
        completed = subprocess.run(
            [sys.executable, str(self.root / "manage.py"), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=self.root,
            env=self.environment,
        )
        result = json.loads(completed.stdout)
        assert result["ok"], result
        return result["result"]

    @asynccontextmanager
    async def host(self, role):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        environment = self.environment | {"ACCEPTANCE_HOST": role}
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(self.root / "manage.py"), "serve", "mcp"],
            cwd=str(self.root),
            env=environment,
        )
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            await session.initialize()
            yield session


async def tool(session, operation, **arguments):
    """Decode the real MCP response without bypassing the common service boundary."""
    response = await session.call_tool(f"sample_{operation}", arguments)
    envelope = json.loads(response.content[0].text)
    assert response.isError == (not envelope["ok"])
    assert response.structuredContent == envelope
    return envelope


async def successful_tool(session, operation, **arguments):
    response = await tool(session, operation, **arguments)
    assert response["ok"], response
    return response["result"]
