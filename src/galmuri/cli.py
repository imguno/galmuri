"""Portable module CLI for project creation, execution and exposure composition."""

import argparse
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and run document service projects",
        epilog="Start with: python -m galmuri startproject example",
    )
    parser.add_argument("--project", default=".", help="Project containing config/settings.py")
    commands = parser.add_subparsers(dest="command", required=True)
    from galmuri.commands.accounts import register
    from galmuri.commands.scaffolding import register as register_scaffolding

    register_scaffolding(commands)
    register(commands)
    sync = commands.add_parser("sync", help="Collect and process pending documents")
    sync.add_argument("--app")
    commands.add_parser("activate", help="Explicitly activate changed app definitions")
    worker = commands.add_parser("worker", help="Run a local or remote execution worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--remote", help="HTTP coordinator URL")
    worker.add_argument("--token-file", type=Path)
    worker.add_argument("--worker-id", default=f"{socket.gethostname()}:{os.getpid()}")
    index = commands.add_parser("index", help="Run durable embedding/vector projection work")
    index.add_argument("--app")
    index.add_argument("--worker-id", default=f"index:{socket.gethostname()}:{os.getpid()}")
    execution = index.add_mutually_exclusive_group()
    execution.add_argument("--once", action="store_true")
    execution.add_argument(
        "--drain", action="store_true", help="Run currently ready work then exit"
    )
    for command in ("reindex", "index-status"):
        index_command = commands.add_parser(command)
        index_command.add_argument("--app")
        if command == "reindex":
            index_command.add_argument("--request-id")
    commands.add_parser("index-retry").add_argument("job_id")
    scheduler = commands.add_parser("scheduler", help="Run app schedules without a server")
    scheduler.add_argument("--once", action="store_true")
    serve = commands.add_parser("serve", help="Start a configured exposure adapter")
    serve.add_argument("adapter", nargs="?", default="http")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--workers", type=int, default=1)
    call = commands.add_parser("call", help="Call the common exposure service through CLI")
    call.add_argument("operation")
    call.add_argument("--params", default="{}", help="JSON object")
    call.add_argument("--app")
    call.add_argument("--query")
    call.add_argument("--mode", choices=("lexical", "vector", "hybrid"))
    return parser


def main(argv=None, project_root: Path | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        from galmuri.commands.scaffolding import COMMANDS as SCAFFOLDING_COMMANDS
        from galmuri.commands.scaffolding import run as scaffolding_command

        if args.command in SCAFFOLDING_COMMANDS:
            return scaffolding_command(args, project_root or args.project)
        from galmuri.configuration.project import load_project

        project = load_project(project_root or args.project)
        from galmuri.commands.accounts import COMMANDS
        from galmuri.commands.accounts import run as account_command

        if args.command in COMMANDS:
            return account_command(args, project)
        if args.command == "worker" and args.remote:
            from galmuri.workers.remote import HttpWorker

            token = (
                args.token_file.read_text(encoding="utf-8").strip()
                if args.token_file
                else os.environ.get("FRAMEWORK_TOKEN", "")
            )
            if not token:
                raise ValueError("Remote worker requires --token-file or FRAMEWORK_TOKEN")
            worker = HttpWorker(
                args.remote, token, {app.name: app for app in project.apps}, args.worker_id
            )
            while True:
                worked = worker.run_once()
                if args.once:
                    return 0
                if not worked:
                    time.sleep(0.2)
        runtime = project.runtime(activate=args.command == "activate")
        from galmuri.contracts.documents import Principal

        local_operator = (
            Principal("local-operator", administrator=True)
            if project.identity is not None
            else project.principal
        )
        principal = project.caller() if args.command in {"call", "serve"} else local_operator
        if args.command == "index":
            if runtime.indexing is None:
                raise ValueError("This backend does not support vector projection workers")
            while True:
                worked = runtime.indexing.work_once(args.worker_id, app_name=args.app)
                if args.once or (args.drain and not worked):
                    print(json.dumps(runtime.indexing.status(args.app)))
                    return 0
                if not worked:
                    time.sleep(0.2)
        if args.command in {"reindex", "index-status", "index-retry"}:
            from galmuri.exposure.cli import CliAdapter
            from galmuri.exposure.service import Service

            params = (
                {"job_id": args.job_id}
                if args.command == "index-retry"
                else ({"app": args.app} if args.app else {})
            )
            operation = {
                "reindex": "reindex",
                "index-status": "index_status",
                "index-retry": "index_retry",
            }[args.command]
            if args.command == "reindex" and args.request_id is not None:
                params["request_id"] = args.request_id
            return CliAdapter(
                Service(runtime, identity=project.identity), principal=local_operator
            ).execute(operation, params, output=sys.stdout)
        if args.command == "activate":
            print(json.dumps({"activated": list(runtime.apps)}))
            return 0
        if args.command == "sync":
            from galmuri.exposure.cli import CliAdapter
            from galmuri.exposure.service import Service

            params = {"app": args.app} if args.app else {}
            return CliAdapter(
                Service(runtime, identity=project.identity), principal=local_operator
            ).execute("sync", params, output=sys.stdout)
        elif args.command == "worker":
            while True:
                worked = runtime.work_once(args.worker_id)
                if args.once:
                    return 0
                if not worked:
                    time.sleep(0.2)
        elif args.command == "scheduler":
            while True:
                runtime.tick()
                if args.once:
                    return 0
                time.sleep(0.5)
        else:
            from galmuri.exposure.service import Service

            service = Service(runtime, identity=project.identity)
            if args.command == "call":
                from galmuri.exposure.cli import CliAdapter

                params = json.loads(args.params)
                if not isinstance(params, dict):
                    raise ValueError("--params must be a JSON object")
                if args.app:
                    params["app"] = args.app
                if args.query is not None:
                    params["query"] = args.query
                if args.mode is not None:
                    params["mode"] = args.mode
                return CliAdapter(service, principal=principal).execute(
                    args.operation, params, output=sys.stdout
                )
            return _serve(args, project, service, runtime)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _serve(args, project, service, runtime) -> int:
    from galmuri.exposure.registry import HostContext, default_registry
    from galmuri.hosting.background import BackgroundHost

    registry = default_registry()
    for name, factory in project.adapters.items():
        registry.register(name, factory)
    options = dict(project.exposures.get(args.adapter, {}))
    for name in ("host", "port"):
        value = getattr(args, name)
        if value is not None:
            options[name] = value
    context = HostContext(project.caller(), project.authenticator())
    adapter = registry.compose(args.adapter, service, context, **options)
    if project.identity is None:
        print(f"Host token file: {project.root / '.runtime' / 'admin.token'}", file=sys.stderr)
    with BackgroundHost(runtime, args.workers):
        adapter.run()
    return 0
