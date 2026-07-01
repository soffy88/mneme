"""Auto-split from hicode whl."""

from __future__ import annotations
from typing import Any
from ._exceptions import OprimError
from ._protocols import McpClientHandle

class McpOprimError(OprimError):
    """MCP 请求失败。"""

async def mcp_call_tool(
    name: str,
    *,
    arguments: dict[str, Any],
    client: McpClientHandle,
) -> dict[str, Any]:
    """单次调用 MCP 工具，返回结果。

    Args:
        name: 工具名称（来自 mcp_list_tools 返回的 name 字段）。
        arguments: 工具参数 dict（符合 inputSchema）。
        client: MCP client handle。

    Returns:
        工具结果 dict，含：
          - content (list): 内容块列表，每项含 type 和 text/data
          - isError (bool): 工具是否报告了错误

    Raises:
        McpOprimError: MCP 请求失败或工具不存在。

    Example:
        >>> result = await mcp_call_tool(
        ...     "search_web",
        ...     arguments={"query": "python asyncio"},
        ...     client=client,
        ... )
        >>> result["content"][0]["text"]
        'Python asyncio documentation...'
    """
    try:
        result = await client.call_tool(name, arguments)
    except Exception as e:
        raise McpOprimError(f"mcp_call_tool '{name}' failed", cause=e)

    if not isinstance(result, dict):
        return {"content": [{"type": "text", "text": str(result)}], "isError": False}

    # 标准化：确保 content 字段存在
    if "content" not in result:
        result = {"content": [{"type": "text", "text": str(result)}], "isError": False}

    return result
