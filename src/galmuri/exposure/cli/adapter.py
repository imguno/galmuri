"""Local CLI identity is host configuration, never command parameters."""

import json
import sys

from galmuri.contracts.documents import Principal


class CliAdapter:
    def __init__(self, service, *, principal=None):
        self.service = service
        self.principal = principal or Principal()

    def execute(self, operation, params, *, output=None):
        response = self.service.call(operation, params, self.principal)
        print(json.dumps(response, ensure_ascii=False), file=output or sys.stdout)
        return 0 if response["ok"] else 1

    def run(self):
        """Read one JSON command per line; useful as a composable local adapter."""
        for line in sys.stdin:
            try:
                command = json.loads(line)
                operation, params = command["operation"], command.get("params", {})
            except (ValueError, TypeError, KeyError):
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "code": "invalid_request",
                                "message": "Invalid command envelope",
                            },
                        }
                    )
                )
                continue
            self.execute(operation, params)
