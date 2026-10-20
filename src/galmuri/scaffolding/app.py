"""Create one source app without loading or editing project settings."""

from pathlib import Path

from galmuri.scaffolding.generation import checked_path, require_complete, validate_name, write_tree
from galmuri.scaffolding.templates import basic, sample
from galmuri.scaffolding.templates import process as processing
from galmuri.scaffolding.templates import retrieval as semantic


def app_contents(name: str, *, process: bool = False) -> dict[str, str]:
    app = basic.APP.replace("sample = App(", f"{name} = App(").replace(
        'name="sample"', f'name="{name}"'
    )
    contents = {
        "__init__.py": "",
        "app.py": app,
        "source/__init__.py": "",
        "source/local.py": basic.SOURCE,
        "skills/usage.md": basic.GUIDE,
        "fixtures/welcome.md": sample.WELCOME,
        "fixtures/clinic.md": semantic.CLINIC,
    }
    if process:
        contents["app.py"] = app.replace(
            "from .source.local import source",
            "from .source.local import source\nfrom .process import process",
        ).replace(f'    name="{name}",', f'    name="{name}",\n    process=process,')
        contents.update(
            {
                "process.py": processing.BINDING,
                "views/__init__.py": "",
                "views/normalization.py": processing.NORMALIZATION,
                "views/metadata.py": processing.METADATA.replace(
                    '"pipeline": "sample"', f'"pipeline": "{name}"'
                ),
            }
        )
    return contents


def create_app(root: str | Path, name: str, *, process: bool = False) -> Path:
    validate_name(name)
    project = checked_path(root)
    require_complete(project / ".project.json")
    for relative in ("manage.py", "config/settings.py", "apps/__init__.py"):
        path = checked_path(project / relative)
        if not path.is_file():
            raise ValueError(f"Expected a project containing {relative}: {project}")
    return write_tree(
        project / "apps" / name,
        app_contents(name, process=process),
        manifest_name=".app.json",
    )
