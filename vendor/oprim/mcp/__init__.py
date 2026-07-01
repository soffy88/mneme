"""
oprim.mcp — MCP (Model Context Protocol) support.
================================================
Includes both server implementation and atomic client operations (oprims).
"""

from __future__ import annotations

from typing import Any

from oprim._exceptions import OprimError
from oprim._protocols import McpClientHandle
from oprim.mcp.mcp_server import create_mcp_server, register_tool


class McpOprimError(OprimError):
    """MCP 请求失败。"""


async def mcp_list_tools(
    *,
    client: McpClientHandle,
) -> list[dict[str, Any]]:
    """单次列出 MCP server 提供的所有工具。"""
    try:
        tools = await client.list_tools()
    except Exception as e:
        raise McpOprimError("mcp_list_tools failed", cause=e)

    normalized = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        normalized.append({
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema") or t.get("input_schema") or {},
        })
    return normalized


async def mcp_call_tool(
    name: str,
    *,
    arguments: dict[str, Any],
    client: McpClientHandle,
) -> dict[str, Any]:
    """单次调用 MCP 工具，返回结果。"""
    try:
        result = await client.call_tool(name, arguments)
    except Exception as e:
        raise McpOprimError(f"mcp_call_tool '{name}' failed", cause=e)

    if not isinstance(result, dict):
        return {"content": [{"type": "text", "text": str(result)}], "isError": False}

    if "content" not in result:
        result = {"content": [{"type": "text", "text": str(result)}], "isError": False}

    return result


__all__ = [
    "create_mcp_server",
    "register_tool",
    "McpOprimError",
    "mcp_list_tools",
    "mcp_call_tool",
]
