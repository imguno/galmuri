import io
import json

from galmuri.cli import main
from galmuri.contracts.documents import Principal
from galmuri.exposure.auth import TokenAuthenticator
from galmuri.exposure.registry import HostContext, default_registry
from galmuri.scaffolding import create_project


def test_serve_cli_uses_host_principal_without_network_auth_kwargs(tmp_path, monkeypatch, capsys):
    root = create_project(tmp_path / "cli_host", retrieval=False)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"operation":"capabilities"}\n'))
    assert main(["serve", "cli", "--workers", "0"], project_root=root) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_custom_adapter_receives_only_explicit_configuration():
    registry = default_registry()
    received = {}

    def custom(service, *, marker):
        received.update(service=service, marker=marker)
        return object()

    registry.register("custom", custom)
    context = HostContext(Principal(), TokenAuthenticator())
    sentinel = object()
    registry.compose("custom", sentinel, context, marker="selected")
    assert received == {"service": sentinel, "marker": "selected"}


def test_cli_sync_cannot_bypass_management_authorization(tmp_path, capsys):
    root = create_project(tmp_path / "restricted_cli", retrieval=False)
    settings = root / "config/settings.py"
    settings.write_text(
        settings.read_text(encoding="utf-8") + "\nLOCAL_PRINCIPAL = Principal()\n", encoding="utf-8"
    )
    assert main(["sync"], project_root=root) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "forbidden"
