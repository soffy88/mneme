from __future__ import annotations

from collections.abc import Callable

# Per spec: use official mcp.server.fastmcp.FastMCP (NOT the fastmcp community package)
from mcp.server.fastmcp import FastMCP


def create_mcp_server(name: str, version: str) -> FastMCP:
    """Create and return a FastMCP server instance.

    Note: The `version` parameter is accepted for API compatibility but is
    intentionally ignored. mcp SDK 1.27.x FastMCP.__init__() does not accept
    a `version` kwarg; pass version information via server metadata if needed.
    """
    return FastMCP(name)


def register_tool(
    server: FastMCP,
    name: str,
    fn: Callable,
    description: str | None = None,
) -> None:
    """Register *fn* as a tool on *server* under *name*.

    Args:
        server: FastMCP server returned by create_mcp_server().
        name: Tool name (used by MCP clients).
        fn: The callable to expose.
        description: Human-readable description of the tool.
    """
    decorator = server.tool(name=name, description=description or "")
    decorator(fn)
