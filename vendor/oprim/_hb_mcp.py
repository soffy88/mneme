"""H-B G组: MCP IO 扩展 (2)
mcp_connect / load_custom_tool
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._exceptions import OprimError


class McpOprimError(OprimError):
    """MCP 连接/加载失败。"""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class McpSession:
    """MCP server 连接会话句柄。"""
    server_url: str
    _session: Any = field(repr=False, default=None)
    _transport: Any = field(repr=False, default=None)

    async def request(self, method: str, params: dict) -> Any:
        """发送 JSON-RPC 请求，返回结果。"""
        if self._session is None:
            raise McpOprimError("McpSession not connected")
        return await self._session.request(method, params)

    async def close(self) -> None:
        """关闭连接。"""
        if self._session is not None:
            try:
                await self._session.aclose()
            except Exception:
                pass
        if self._transport is not None:
            try:
                await self._transport.aclose()
            except Exception:
                pass


@dataclass
class Tool:
    """工具定义（.opencode/tools/*.ts 或 JSON schema）。"""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict | None = None
    source_path: str = ""


# ---------------------------------------------------------------------------
# mcp_connect
# ---------------------------------------------------------------------------

async def mcp_connect(server_url: str, *, timeout: float = 30) -> McpSession:
    """连接 MCP server，握手，返回 session handle。

    支持 HTTP/SSE (http[s]://) 和 stdio (stdio:// 前缀) 两种 transport。

    Args:
        server_url: MCP server URL 或 stdio 描述符。
        timeout: 连接超时秒数，默认 30。

    Returns:
        McpSession 连接句柄。

    Raises:
        ValueError: URL 非法。
        McpOprimError: 连接失败或握手失败。
        TimeoutError: 超时。

    Example:
        >>> session = await mcp_connect("https://mcp.example.com/sse")
        >>> tools = await session.request("tools/list", {})
    """
    if not server_url:
        raise ValueError("server_url must not be empty")
    if not (
        server_url.startswith("http://")
        or server_url.startswith("https://")
        or server_url.startswith("stdio://")
    ):
        raise ValueError(
            f"server_url must start with http://, https://, or stdio://: {server_url!r}"
        )

    if server_url.startswith("stdio://"):
        return await _connect_stdio(server_url, timeout=timeout)
    return await _connect_sse(server_url, timeout=timeout)


async def _connect_sse(url: str, *, timeout: float) -> McpSession:
    try:
        from mcp.client.sse import sse_client
        from mcp import ClientSession
    except ImportError as e:
        raise McpOprimError("mcp package not installed or missing sse client", cause=e)

    try:
        transport = await asyncio.wait_for(sse_client(url).__aenter__(), timeout=timeout)
        read, write = transport
        session = await asyncio.wait_for(
            ClientSession(read, write).__aenter__(), timeout=timeout
        )
        await asyncio.wait_for(session.initialize(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"mcp_connect timed out after {timeout}s: {url}") from e
    except McpOprimError:
        raise
    except Exception as e:
        raise McpOprimError(f"mcp_connect failed for {url}: {e}", cause=e)

    return McpSession(server_url=url, _session=session, _transport=None)


async def _connect_stdio(url: str, *, timeout: float) -> McpSession:
    # stdio:// URL format: stdio://path/to/server?arg1=val1
    # Strip prefix and use path as command
    cmd = url[len("stdio://"):]
    try:
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession, StdioServerParameters
    except ImportError as e:
        raise McpOprimError("mcp package not installed or missing stdio client", cause=e)

    try:
        params = StdioServerParameters(command=cmd, args=[], env=None)
        transport_cm = stdio_client(params)
        transport = await asyncio.wait_for(transport_cm.__aenter__(), timeout=timeout)
        read, write = transport
        session = await asyncio.wait_for(
            ClientSession(read, write).__aenter__(), timeout=timeout
        )
        await asyncio.wait_for(session.initialize(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"mcp_connect (stdio) timed out after {timeout}s") from e
    except McpOprimError:
        raise
    except Exception as e:
        raise McpOprimError(f"mcp_connect (stdio) failed: {e}", cause=e)

    return McpSession(server_url=url, _session=session, _transport=None)


# ---------------------------------------------------------------------------
# load_custom_tool
# ---------------------------------------------------------------------------

async def load_custom_tool(path: Path) -> Tool:
    """加载 .opencode/tools/*.ts 自定义 tool 定义。

    支持格式：
    - JSON/JSONC：直接解析 schema
    - TypeScript/JavaScript：提取 JSDoc 注释或 JSON schema 块
    - YAML：通过 pyyaml 解析（可选依赖）

    Args:
        path: tool 定义文件路径（.ts/.js/.json/.yaml/.yml）。

    Returns:
        Tool 对象（name, description, input_schema）。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 定义文件格式非法或无法提取 schema。

    Example:
        >>> tool = await load_custom_tool(Path(".opencode/tools/search.ts"))
        >>> tool.name
        'search'
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"tool file not found: {path}")

    loop = asyncio.get_event_loop()

    def _load() -> Tool:
        suffix = p.suffix.lower()
        content = p.read_text(encoding="utf-8")

        if suffix in (".json",):
            return _parse_json_tool(content, p)
        if suffix in (".yaml", ".yml"):
            return _parse_yaml_tool(content, p)
        if suffix in (".ts", ".js", ".mjs"):
            return _parse_ts_tool(content, p)
        # fallback: try JSON
        try:
            return _parse_json_tool(content, p)
        except Exception:
            raise ValueError(f"unsupported or unrecognizable tool file format: {p.suffix}")

    return await loop.run_in_executor(None, _load)


def _parse_json_tool(content: str, path: Path) -> Tool:
    # Strip JSONC comments
    lines = [ln for ln in content.splitlines() if not ln.strip().startswith("//")]
    data = json.loads("\n".join(lines))
    return Tool(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        input_schema=data.get("input_schema") or data.get("inputSchema") or data.get("schema", {}),
        output_schema=data.get("output_schema"),
        source_path=str(path),
    )


def _parse_yaml_tool(content: str, path: Path) -> Tool:
    try:
        import yaml
    except ImportError as e:
        raise ValueError("pyyaml not installed for YAML tool files") from e
    data = yaml.safe_load(content) or {}
    return Tool(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        input_schema=data.get("input_schema") or data.get("inputSchema") or {},
        source_path=str(path),
    )


def _parse_ts_tool(content: str, path: Path) -> Tool:
    """Extract tool metadata from TypeScript/JS tool files.

    Looks for:
    1. export const definition = { name, description, inputSchema }
    2. Inline JSON schema block: /* @schema { ... } */
    3. JSDoc @name / @description tags
    """
    import re

    # Try to find JSON schema block in comments
    schema_match = re.search(r"/\*\s*@schema\s*(\{.*?\})\s*\*/", content, re.DOTALL)
    if schema_match:
        try:
            schema_data = json.loads(schema_match.group(1))
            return Tool(
                name=schema_data.get("name", path.stem),
                description=schema_data.get("description", ""),
                input_schema=schema_data.get("inputSchema") or schema_data.get("input_schema") or {},
                source_path=str(path),
            )
        except json.JSONDecodeError:
            pass

    # Try to extract from export const definition = { ... }
    def_match = re.search(
        r"export\s+(?:const|let|var)\s+\w+\s*=\s*(\{[^;]+\})\s*;?",
        content, re.DOTALL
    )
    if def_match:
        # Try to parse as JSON (after replacing single-quoted strings)
        raw = def_match.group(1)
        # Simple extraction of name and description from TS object literal
        name_m = re.search(r'name\s*:\s*["\']([^"\']+)["\']', raw)
        desc_m = re.search(r'description\s*:\s*["\']([^"\']+)["\']', raw)
        return Tool(
            name=name_m.group(1) if name_m else path.stem,
            description=desc_m.group(1) if desc_m else "",
            input_schema={},
            source_path=str(path),
        )

    # Fallback: use filename
    return Tool(
        name=path.stem,
        description="",
        input_schema={},
        source_path=str(path),
    )
