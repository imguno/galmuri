"""Build from clean source and from its sdist, then compare both against source."""

import subprocess
import sys
import tomllib
from hashlib import sha256

from tools.release.artifacts import unpack, wheel_payload
from tools.release.source import compare_source, snapshot


def run(*arguments, cwd):
    subprocess.run([str(value) for value in arguments], cwd=cwd, check=True)


def build(root, work, distribution, package):
    work.mkdir(parents=True)
    source, output = work / "source", work / "artifacts"
    snapshot(root, source)
    run(sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", output, cwd=source)
    wheel = next(output.glob("*.whl"))
    sdist = next(output.glob("*.tar.gz"))
    expanded = unpack(sdist, work / "unpacked")
    run(sys.executable, "-m", "build", "--wheel", "--outdir", work / "rebuilt", cwd=expanded)
    version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    payload = wheel_payload(wheel, distribution, package, version)
    rebuilt = wheel_payload(next((work / "rebuilt").glob("*.whl")), distribution, package, version)
    if not payload or payload != rebuilt:
        raise ValueError("Source wheel and sdist-rebuilt wheel package bytes differ")
    compare_source(source, package, payload)
    run(sys.executable, "-m", "twine", "check", "--strict", wheel, sdist, cwd=work)
    return (
        wheel,
        sdist,
        {
            "distribution": distribution,
            "package_files": len(payload),
            "source_bytes_checked": True,
            "sdist_rebuild_payload_equal": True,
            "sha256": {path.name: sha256(path.read_bytes()).hexdigest() for path in (wheel, sdist)},
            "passed": True,
        },
    )
