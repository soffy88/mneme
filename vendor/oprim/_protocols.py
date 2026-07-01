"""
oprim._protocols — 外部 handle 的 Protocol 定义
================================================
M4 Owner 裁决实现：lsp_* / mcp_* oprim 的 server/client 参数
类型是 Protocol，由调用方（obase.lsp / obase.mcp_client）注入 handle。
oprim 内部不 import obase，只调用 handle 上的方法。V1 守住。

生产使用：
    from obase.lsp import LspManager
    server = LspManager().connect("python", cwd="/project")
    diags = lsp_diagnostics("src/main.py", server=server)

测试使用：
    server = MockLspServer(...)
    diags = lsp_diagnostics("src/main.py", server=server)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LspServerHandle(Protocol):
    """
    obase.lsp 返回的语言服务器连接句柄的 Protocol。
    oprim 只调用此 Protocol 上声明的方法，不 import obase.lsp。

    生产实现由 obase.lsp.LspManager 提供。
    """

    async def request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        """发送单次 JSON-RPC 请求，返回结果。

        Args:
            method: LSP 方法名，如 "textDocument/diagnostics"。
            params: 请求参数 dict。

        Returns:
            LSP 响应 result 字段（已 JSON 解析）。

        Raises:
            LspError: LSP 返回 error 对象时。
        """
        ...  # pragma: no cover

    @property
    def root_uri(self) -> str:
        """workspace 根 URI，如 "file:///project"。"""
        ...  # pragma: no cover


@runtime_checkable
class StreamingLLMCaller(Protocol):
    """
    流式 LLM 调用 Protocol（obase.ProviderRegistry 流式变体）。
    oprim.llm_stream 接受此类型注入，不 import provider SDK。
    """

    async def __call__(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> "AsyncIterator[dict]":
        """
        流式调用 LLM，yield Delta dict：
          {"type": "text_delta", "text": str}
          {"type": "tool_use", "id": str, "name": str, "input": dict}
          {"type": "usage", "input_tokens": int, "output_tokens": int}
          {"type": "stop", "stop_reason": str}
        """
        ...  # pragma: no cover


@runtime_checkable
class EmbedCaller(Protocol):
    """
    嵌入向量调用 Protocol（obase.ProviderRegistry 嵌入变体）。
    oprim.embed_text 接受此类型注入。
    """

    async def __call__(
        self,
        *,
        text: str,
        model: str = "text-embedding-3-small",
    ) -> list[float]:
        """返回嵌入向量（float list）。"""
        ...  # pragma: no cover


@runtime_checkable
class SearchCaller(Protocol):
    """
    Web 搜索 Protocol（obase.search 或外部搜索 API 适配器）。
    oprim.web_search 接受此类型注入。
    """

    async def __call__(
        self,
        *,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        返回搜索结果列表，每项含：
          {"title": str, "url": str, "snippet": str}
        """
        ...  # pragma: no cover


@runtime_checkable
class PersistenceHandle(Protocol):
    """
    持久化存储 Protocol（obase.persistence 适配器）。
    oprim.snapshot_conversation 接受此类型注入，不 import obase.persistence。
    """

    async def save(self, *, key: str, value: str) -> str:
        """
        存储 key-value 数据，返回存储后的 revision id。

        Args:
            key: 存储键（如 "session:{id}:snapshot:{rev}"）。
            value: 序列化后的字符串（JSON）。

        Returns:
            revision id（str），供调用方做 undo/rewind。
        """
        ...  # pragma: no cover

    async def load(self, *, key: str) -> str | None:
        """
        读取 key 对应的值，不存在返回 None。
        """
        ...  # pragma: no cover


@runtime_checkable
class McpClientHandle(Protocol):
    """
    obase.mcp_client 返回的 MCP 连接句柄的 Protocol。
    oprim 只调用此 Protocol 上声明的方法，不 import obase.mcp_client。

    生产实现由 obase.mcp_client.McpClient 提供。
    """

    async def list_tools(self) -> list[dict[str, Any]]:
        """列出所有可用工具的 schema 列表。

        Returns:
            list of {"name": str, "description": str, "inputSchema": dict}
        """
        ...  # pragma: no cover

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """调用指定工具。

        Args:
            name: 工具名称。
            arguments: 工具参数。

        Returns:
            工具返回结果 dict，含 "content" 字段。

        Raises:
            McpError: 工具调用失败时。
        """
        ...  # pragma: no cover

# --- Legacy Protocols ---

class HttpClient(Protocol):
    """Protocol for async HTTP client operations."""

    async def get(self, url: str, **kwargs: Any) -> dict | list | None: ...
    async def post(self, url: str, **kwargs: Any) -> dict | list | None: ...


class DbExecutor(Protocol):
    """Protocol for async database operations."""

    async def fetch_one(self, query: str, params: dict | None = None) -> dict | None: ...
    async def fetch_all(self, query: str, params: dict | None = None) -> list[dict]: ...
    async def execute(self, query: str, params: dict | None = None) -> int: ...


class CacheClient(Protocol):
    """Protocol for async cache (Redis) operations."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    async def publish(self, channel: str, message: str) -> None: ...
