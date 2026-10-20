"""Generation commands are independent of project imports and runtime composition."""

from galmuri.scaffolding.app import create_app
from galmuri.scaffolding.project import create_project, start_project

COMMANDS = frozenset({"startproject", "startapp", "new"})


def register(commands):
    project = commands.add_parser("startproject", help="Create an empty project")
    project.add_argument("name")
    project.add_argument("directory", nargs="?", help="New destination directory")
    app = commands.add_parser("startapp", help="Create an app; register it in config/settings.py")
    app.add_argument("name")
    app.add_argument("--process", action="store_true", help="Include custom processing functions")
    new = commands.add_parser("new", help="Generate a sample project shortcut")
    new.add_argument("path")
    presets = new.add_mutually_exclusive_group()
    presets.add_argument(
        "--retrieval",
        action="store_true",
        default=None,
        help="Generate explicit parser/policy and Qdrant configuration",
    )
    presets.add_argument(
        "--lexical",
        dest="retrieval",
        action="store_false",
        help="Generate the explicit-handler keyword-only tutorial",
    )
    presets.add_argument(
        "--process", action="store_true", help="Generate a runnable custom process pipeline"
    )
    new.set_defaults(retrieval=None)


def run(args, project_root) -> int:
    if args.command == "startproject":
        print(start_project(args.name, args.directory))
    elif args.command == "startapp":
        print(create_app(project_root, args.name, process=args.process))
        print(
            "Register this app in config/settings.py "
            "(keep existing APPS entries and add the new reference):"
        )
        print(f'APPS = ["apps.{args.name}.app:{args.name}"]')
    else:
        print(create_project(args.path, retrieval=args.retrieval, process=args.process))
    return 0
