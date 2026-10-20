"""Verify Galmuri and Duru distributions and export only release artifacts."""

import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.release.building import build
from tools.release.installation import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-access", dest="duru", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path(".verification/release"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="galmuri-release-") as directory:
        work = Path(directory)
        access = build(args.duru.resolve(), work / "access", "duru", "duru")
        galmuri = build(root, work / "galmuri", "galmuri", "galmuri")
        installation = verify((access[0], galmuri[0]), work / "installation")
        for artifact in (*access[:2], *galmuri[:2]):
            shutil.copy2(artifact, output / artifact.name)
        result = {
            "passed": True,
            "packages": [access[2], galmuri[2]],
            "installation": installation,
        }
        (output / "checks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "output": str(output)}))


if __name__ == "__main__":
    main()
