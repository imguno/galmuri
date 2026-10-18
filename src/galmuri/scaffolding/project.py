"""Create a project without overwriting user-authored files."""

import json
from pathlib import Path

from galmuri.scaffolding.templates import basic, configuration, sample
from galmuri.scaffolding.templates import process as processing
from galmuri.scaffolding.templates import retrieval as semantic


def create_project(
    path: str | Path, *, retrieval: bool | None = None, process: bool = False
) -> Path:
    if process and retrieval is not None:
        raise ValueError("Choose the process preset or an explicit retrieval/lexical preset")
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=False)
    contents = {
        "manage.py": configuration.MANAGE,
        "config/__init__.py": "",
        "config/settings.py": configuration.SETTINGS,
        "apps/__init__.py": "",
        "apps/sample/__init__.py": "",
        "apps/sample/app.py": sample.APP,
        "apps/sample/source/__init__.py": "",
        "apps/sample/source/local.py": sample.SOURCE,
        "apps/sample/ingestion/__init__.py": "",
        "apps/sample/ingestion/documents.py": sample.INGESTION,
        "apps/sample/policies/__init__.py": "",
        "apps/sample/policies/collection.py": sample.POLICY,
        "apps/sample/skills/usage.md": sample.GUIDE,
        "apps/sample/fixtures/welcome.md": sample.WELCOME,
        "apps/sample/fixtures/development.dev.md": sample.DEVELOPMENT,
        ".gitignore": ".runtime/\n__pycache__/\n.venv/\n",
        "README.md": (
            "# Source project\n\n"
            "Run `python manage.py sync`, then `python manage.py serve http`.\n"
            "Use `python manage.py call search --app sample --query welcome`.\n"
            "See `python manage.py --help` for workers and exposure adapters.\n"
        ),
    }
    if retrieval is None:
        contents["config/settings.py"] = configuration.ACCOUNT_SETTINGS
        contents["apps/sample/app.py"] = basic.APP
        contents["apps/sample/source/local.py"] = basic.SOURCE
        contents["apps/sample/skills/usage.md"] = basic.GUIDE
        contents["apps/sample/fixtures/clinic.md"] = semantic.CLINIC
        contents["README.md"] = basic.README
        for relative in (
            "apps/sample/ingestion/__init__.py",
            "apps/sample/ingestion/documents.py",
            "apps/sample/policies/__init__.py",
            "apps/sample/policies/collection.py",
            "apps/sample/fixtures/development.dev.md",
        ):
            contents.pop(relative)
    elif retrieval:
        contents["apps/sample/app.py"] = sample.APP.replace(
            "from .source.local import source",
            "from .source.local import source\nfrom .retrieval.configuration import retrieval",
        ).replace('    name="sample",', '    name="sample",\n    retrieval=retrieval,')
        contents.update(
            {
                "apps/sample/retrieval/__init__.py": "",
                "apps/sample/retrieval/configuration.py": semantic.CONFIGURATION,
                "apps/sample/skills/usage.md": semantic.GUIDE,
                "apps/sample/fixtures/clinic.md": semantic.CLINIC,
                "compose.yaml": semantic.COMPOSE,
                "README.md": semantic.README,
            }
        )
    if process:
        contents["apps/sample/app.py"] = basic.APP.replace(
            "from .source.local import source",
            "from .source.local import source\nfrom .process import process",
        ).replace('    name="sample",', '    name="sample",\n    process=process,')
        contents.update(
            {
                "apps/sample/process.py": processing.BINDING,
                "apps/sample/views/__init__.py": "",
                "apps/sample/views/normalization.py": processing.NORMALIZATION,
                "apps/sample/views/metadata.py": processing.METADATA,
                "README.md": processing.README,
            }
        )
    manifest = target / ".project.json"
    manifest.write_text(json.dumps({"schema": 1, "state": "PREPARING"}), encoding="utf-8")
    try:
        for relative, content in contents.items():
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
    except OSError:
        manifest.write_text(json.dumps({"schema": 1, "state": "FAILED"}), encoding="utf-8")
        raise
    manifest.write_text(json.dumps({"schema": 1, "state": "COMPLETE"}), encoding="utf-8")
    return target
