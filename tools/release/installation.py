"""Install both artifacts with real runtime dependencies into a fresh environment."""

import subprocess
import sys
import venv
from pathlib import Path

from tools.release.building import run


def verify(wheels, directory):
    directory.mkdir()
    environment = directory / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run(python, "-m", "pip", "install", *wheels, cwd=directory)
    run(python, "-m", "pip", "check", cwd=directory)
    script = Path(__file__).with_name("smoke.py")
    subprocess.run([str(python), "-I", str(script)], cwd=directory, check=True)
    return {"fresh_environment": True, "runtime_dependencies_installed": True, "passed": True}
