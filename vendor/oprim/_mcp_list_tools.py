"""Auto-split from hicode whl."""

from __future__ import annotations
from typing import Any
from ._exceptions import OprimError
from ._protocols import McpClientHandle

class McpOprimError(OprimError):
    """MCP 请求失败。"""

async def mcp_list_tools(
    *,
    client: McpClientHandle,
) -> list[dict[str, Any]]:
    """单次列出 MCP server 提供的所有工具。

    Args:
        client: MCP client handle（由 obase.mcp_client 注入）。

    Returns:
        工具 schema 列表，每项含：
          - name (str): 工具名
          - description (str): 工具描述
          - inputSchema (dict): JSON Schema

    Raises:
        McpOprimError: MCP 请求失败。

    Example:
        >>> tools = await mcp_list_tools(client=client)
        >>> [t["name"] for t in tools]
        ['search_web', 'get_weather', 'query_database']
    """
    try:
        tools = await client.list_tools()
    except Exception as e:
        raise McpOprimError("mcp_list_tools failed", cause=e)

    # 标准化字段名（MCP 规范用 inputSchema，部分实现用 input_schema）
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
