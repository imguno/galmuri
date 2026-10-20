"""Create a fresh source snapshot with only declared distribution inputs."""

import shutil

from tools.public_documents import PUBLIC_DOCUMENTS


def snapshot(root, destination):
    destination.mkdir()
    for name in ("pyproject.toml", "MANIFEST.in", "LICENSE", "README.md", "README.ko.md"):
        shutil.copy2(root / name, destination / name)
    (destination / "docs").mkdir()
    for name in PUBLIC_DOCUMENTS:
        shutil.copy2(root / "docs" / name, destination / "docs" / name)
    for name in ("src", "tests", "tools", "skills", "guides"):
        if (root / name).is_dir():
            shutil.copytree(
                root / name,
                destination / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info"),
            )


def compare_source(source, package, payload):
    expected = {
        path.relative_to(source / "src").as_posix(): path.read_bytes()
        for path in (source / "src" / package).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    if expected != {name: data for name, data in payload.items() if name.startswith(package + "/")}:
        raise ValueError("Wheel package files or bytes differ from the source snapshot")
    for name, data in payload.items():
        origin = (
            source / "src" / name
            if name.startswith(package + "/")
            else source / name.split("/share/galmuri/", 1)[1]
        )
        if data != origin.read_bytes():
            raise ValueError(f"Wheel differs from source snapshot: {name}")
    if package == "galmuri":
        required = ["exposure/grpc/exposure.proto"]
        required += [
            f"exposure/dashboard/assets/{name}" for name in ("index.html", "app.js", "style.css")
        ]
        if any(f"galmuri/{name}" not in payload for name in required):
            raise ValueError("Wheel omitted dashboard assets or the gRPC schema")
        if not any(name.endswith("/SKILL.md") for name in payload):
            raise ValueError("Wheel omitted the agent usage skill")
