"""Own the disposable Docker host and generated project used by acceptance."""

import json
import subprocess
import uuid
from pathlib import Path


class Host:
    def __init__(self, image: str, directory: Path):
        self.image, self.directory = image, directory
        self.name = "source-acceptance-" + uuid.uuid4().hex[:12]
        self.project = "/workspace/knowledge"

    def __enter__(self):
        self.directory.mkdir(parents=True)
        self.run(
            "run",
            "-d",
            "--name",
            self.name,
            "--mount",
            f"type=bind,source={self.directory},target=/workspace",
            "--entrypoint",
            "sleep",
            self.image,
            "infinity",
        )
        try:
            self.run("exec", self.name, "python", "-m", "galmuri", "new", self.project, "--lexical")
        except BaseException:
            self.__exit__()
            raise
        return self

    @staticmethod
    def run(*arguments, input=None):
        completed = subprocess.run(
            ["docker", *arguments],
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=180,
        )
        return completed.stdout.strip()

    def configure(self, data: dict):
        settings = """
import os
if os.environ.get("ACCEPTANCE_ROLE") == "public":
    LOCAL_PRINCIPAL = Principal("public-reader")
elif os.environ.get("ACCEPTANCE_ROLE") == "dev":
    LOCAL_PRINCIPAL = Principal("developer", frozenset({"dev"}))
"""
        script = """
import json,sys
from pathlib import Path
data=json.load(sys.stdin)
root=Path(data["root"])
settings=root/"config/settings.py"
settings.write_text(settings.read_text(encoding="utf-8") + data["settings"], encoding="utf-8")
for name, text in data["files"].items():
    (root/"apps/sample/fixtures"/name).write_text(text, encoding="utf-8")
"""
        payload = {"root": self.project, "settings": settings, "files": data}
        self.run("exec", "-i", self.name, "python", "-c", script, input=json.dumps(payload))

    def replace(self, name: str, content: str | None):
        script = (
            "import json,sys\nfrom pathlib import Path\n"
            "name,content=json.load(sys.stdin)\n"
            f"path=Path({self.project!r})/'apps/sample/fixtures'/name\n"
            "if content is None: path.unlink()\n"
            "else: path.write_text(content, encoding='utf-8')\n"
        )
        self.run("exec", "-i", self.name, "python", "-c", script, input=json.dumps([name, content]))

    def sync(self):
        return json.loads(
            self.run("exec", self.name, "python", self.project + "/manage.py", "sync")
        )

    def mcp_arguments(self, role: str):
        return [
            "exec",
            "-i",
            "--env",
            f"ACCEPTANCE_ROLE={role}",
            self.name,
            "python",
            self.project + "/manage.py",
            "serve",
            "mcp",
            "--workers",
            "0",
        ]

    def __exit__(self, *args):
        # Only the UUID-named container created by this object is removed.
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=30)
