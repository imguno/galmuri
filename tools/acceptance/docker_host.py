"""Run CLI and read-only MCP clients against an installed disposable Docker host."""

import json
import subprocess
import uuid


class DockerProject:
    def __init__(self, container, environment=(), *, prefix="acceptance"):
        self.container = container
        self.environment = list(environment)
        self.project = "/workspace/galmuri/.verification/" + prefix + "-" + uuid.uuid4().hex

    def execute(self, *arguments, input=None):
        return subprocess.run(
            [
                "docker",
                "exec",
                *(["-i"] if input is not None else []),
                *self.environment,
                self.container,
                *arguments,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=240,
            input=input,
        ).stdout

    def command(self, *arguments):
        raw = self.execute("python", self.project + "/manage.py", *arguments)
        return json.loads(raw.strip().splitlines()[-1])

    def mcp_arguments(self, role):
        return [
            "exec",
            "-i",
            *self.environment,
            "--env",
            "ACCEPTANCE_ROLE=" + role,
            self.container,
            "python",
            self.project + "/manage.py",
            "serve",
            "mcp",
            "--workers",
            "0",
        ]
