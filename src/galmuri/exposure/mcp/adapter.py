"""Official MCP SDK adapter; stdio caller identity belongs to the host."""

import json

from galmuri.contracts.documents import Principal


class McpAdapter:
    def __init__(self, service, *, principal=None, name="Sources"):
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            raise RuntimeError("Install galmuri[mcp] to use the MCP adapter") from None
        self.service = service
        self.principal = principal or Principal()
        self.server = FastMCP(
            name,
            instructions=(
                "Read each app's description before searching. Document permissions are enforced "
                "for the host-configured caller. Source write requires a current expected version."
            ),
        )
        for app_name, descriptor in service.capabilities(self.principal).items():
            self._register_app(app_name, descriptor)

    def _register_app(self, app_name, descriptor):
        from mcp.types import CallToolResult, TextContent, ToolAnnotations

        service, principal = self.service, self.principal

        def invoke(operation, params) -> CallToolResult:
            envelope = service.call(operation, {"app": app_name, **params}, principal)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(envelope, allow_nan=False))],
                structuredContent=envelope,
                isError=not envelope["ok"],
            )

        def search(query: str, limit: int = 20, mode: str | None = None) -> CallToolResult:
            """Search visible documents. Describe explains supported lexical/vector/hybrid modes."""
            params = {"query": query, "limit": limit}
            if mode is not None:
                params["mode"] = mode
            return invoke("search", params)

        def read(document_key: str) -> CallToolResult:
            """Read a visible document by its stable document key."""
            return invoke("read", {"document_key": document_key})

        def describe() -> CallToolResult:
            """Describe this source, search guidance and currently visible data."""
            return invoke("describe", {})

        def write(document_key: str, content: str, expected_version: str) -> CallToolResult:
            """Write an authorized original source and schedule processing of the new version."""
            return invoke(
                "write",
                {
                    "document_key": document_key,
                    "content": content,
                    "expected_version": expected_version,
                },
            )

        functions = {"search": search, "read": read, "describe": describe, "write": write}
        for operation in descriptor["operations"]:
            writing = operation == "write"
            annotations = ToolAnnotations(
                readOnlyHint=not writing,
                destructiveHint=writing,
                idempotentHint=not writing,
                openWorldHint=writing,
            )
            self.server.tool(name=f"{app_name}_{operation}", annotations=annotations)(
                functions[operation]
            )

    def run(self):
        self.server.run(transport="stdio")

    def serve_forever(self):
        self.run()
