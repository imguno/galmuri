"""Inspect distribution paths, licensing and installed package payload bytes."""

import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import PurePosixPath

PRIVATE = {
    ".git",
    ".venv",
    ".runtime",
    ".verification",
    "__pycache__",
    "docs",
    ".secrets",
    "secrets",
}
PRIVATE_SUFFIXES = {".pyc", ".pyo", ".token", ".pem", ".key", ".sqlite", ".sqlite3", ".db"}


def check_names(names):
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or PRIVATE.intersection(path.parts)
            or path.suffix in PRIVATE_SUFFIXES
            or any(part == ".env" or part.startswith(".env.") for part in path.parts)
        ):
            raise ValueError(f"Unsafe or private distribution member: {name}")


def wheel_payload(path, distribution, package, version):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        check_names(names)
        if sum(name.endswith(".dist-info/licenses/LICENSE") for name in names) != 1:
            raise ValueError("Wheel must include its BSD license")
        metadata = BytesParser().parsebytes(
            archive.read(next(name for name in names if name.endswith(".dist-info/METADATA")))
        )
        if (
            metadata["Name"] != distribution
            or metadata["Version"] != version
            or metadata["License-Expression"] != "BSD-3-Clause"
        ):
            raise ValueError("Distribution name, version or BSD license metadata differs")
        if distribution == "duru" and any(
            "extra ==" not in value for value in metadata.get_all("Requires-Dist", [])
        ):
            raise ValueError("Duru must not gain a runtime dependency")
        return {
            name: archive.read(name)
            for name in names
            if (name.startswith(package + "/") or ".data/data/share/galmuri/skills/" in name)
            and not name.endswith("/")
        }


def unpack(path, destination):
    with tarfile.open(path) as archive:
        check_names(archive.getnames())
        if any(not (member.isfile() or member.isdir()) for member in archive.getmembers()):
            raise ValueError("Source archive contains links or special files")
        archive.extractall(destination, filter="data")
    roots = list(destination.iterdir())
    if len(roots) != 1 or not (roots[0] / "LICENSE").is_file():
        raise ValueError("Source archive must have one root with a license")
    return roots[0]
