"""Like manage.py administration, these commands require trusted local OS access."""

import getpass
import json
import sys
from pathlib import Path

from .credential_files import publish


def register(commands):
    for name in ("createsuperuser", "createuser", "passwd", "login"):
        parser = commands.add_parser(name)
        parser.add_argument("username")
        parser.add_argument("--password-stdin", action="store_true")
        if name == "createuser":
            parser.add_argument("--administrator", action="store_true")
        if name == "login":
            parser.add_argument("--token-file", type=Path, required=True)
    for name in ("disableuser", "enableuser"):
        commands.add_parser(name).add_argument("username")
    commands.add_parser("users")
    commands.add_parser("groups")
    commands.add_parser("creategroup").add_argument("name")
    for name in ("group-add", "group-remove"):
        parser = commands.add_parser(name)
        parser.add_argument("group")
        parser.add_argument("username")
    parser = commands.add_parser("mcp-token")
    parser.add_argument("username")
    parser.add_argument("--name", default="MCP client")
    parser.add_argument("--scope", action="append", choices=("read", "write", "manage"))
    parser.add_argument("--app", action="append")
    parser.add_argument("--ttl", type=int, default=2592000)
    parser.add_argument("--token-file", type=Path, required=True)
    commands.add_parser("logout").add_argument("--token-file", type=Path, required=True)


COMMANDS = frozenset(
    {
        "createsuperuser",
        "createuser",
        "passwd",
        "login",
        "disableuser",
        "enableuser",
        "users",
        "groups",
        "creategroup",
        "group-add",
        "group-remove",
        "mcp-token",
        "logout",
    }
)


def _password(args, *, confirm=False):
    if args.password_stdin:
        value = sys.stdin.readline(4097).rstrip("\r\n")
    else:
        value = getpass.getpass("Password: ")
        if confirm and value != getpass.getpass("Confirm password: "):
            raise ValueError("Passwords do not match")
    if len(value) > 1024:
        raise ValueError("Password exceeds maximum length")
    return value


def _find(records, value, field):
    for row in records:
        if row["id"] == value or row[field].casefold() == value.casefold():
            return row
    raise ValueError("Account or group was not found")


def run(args, project):
    store = project.identity
    if store is None:
        raise ValueError("Set IDENTITY_DATABASE to enable account administration")
    command = args.command
    if command in {"createsuperuser", "createuser"}:
        result = store.create_user(
            args.username,
            _password(args, confirm=True),
            administrator=getattr(args, "administrator", False),
            root=command == "createsuperuser",
        )
    elif command == "users":
        result = store.list_users()
    elif command == "groups":
        result = store.list_groups()
    elif command == "creategroup":
        result = store.create_group(args.name)
    elif command in {"group-add", "group-remove"}:
        user = _find(store.list_users(), args.username, "username")
        group = _find(store.list_groups(), args.group, "name")
        operation = store.add_member if command == "group-add" else store.remove_member
        operation(group["id"], user["id"])
        result = {"user_id": user["id"], "group_id": group["id"]}
    elif command == "login":
        result = publish(store, store.login(args.username, _password(args)), args.token_file)
    elif command == "logout":
        with args.token_file.open(encoding="utf-8") as stream:
            token = stream.read(4097).strip()
        principal = store.authenticate(token)
        store.revoke_token(principal.credential_id, user_id=principal.subject)
        args.token_file.unlink()
        result = {"revoked": True}
    else:
        user = _find(store.list_users(), args.username, "username")
        if command == "passwd":
            store.change_password(user["id"], _password(args, confirm=True))
            result = {"changed": True}
        elif command in {"disableuser", "enableuser"}:
            store.set_user_enabled(user["id"], command == "enableuser")
            result = {"enabled": command == "enableuser"}
        else:
            apps = args.app or ["*"]
            if set(apps) - {app.name for app in project.apps} - {"*"}:
                raise ValueError("Unknown app in token scope")
            credential = store.issue_token(
                user["id"], args.name, scopes=args.scope or ["read"], apps=apps, ttl=args.ttl
            )
            result = publish(store, credential, args.token_file)
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0
