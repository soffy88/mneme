"""Auto-split from hicode whl."""

from __future__ import annotations
from .._exceptions import OprimError, LLMOprimError, BudgetExceededError, PromptOprimError, SearchOprimError, HttpOprimError, SnapshotOprimError
from ._types import LLMResponse, StreamDelta, EmbedResult, ConversationSnapshot, ThinkingResult, SearchResult, HttpResponse
import json
from collections.abc import AsyncIterator
from typing import Any
from .._protocols import EmbedCaller, StreamingLLMCaller
from ._utils import _validate_messages
async def llm_stream(
    messages: list[dict],
    *,
    caller: StreamingLLMCaller,
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    system: str | None = None,
) -> AsyncIterator[StreamDelta]:
    """单次流式 LLM 调用，逐 delta yield 规范化输出。

    async 本性：流式 IO 等待。屏蔽 provider 流格式差异，
    统一输出 StreamDelta（type=text/tool_use/usage/stop）。

    Args:
        messages: 消息列表。
        caller: StreamingLLMCaller Protocol 实例（由调用方注入）。
        tools: 工具 schema 列表（可选）。
        max_tokens: 最大输出 token 数，默认 4096。
        system: system prompt（可选）。

    Yields:
        StreamDelta — type 字段区分内容类型。

    Raises:
        LLMOprimError: 消息格式错误或流式调用失败。

    Example:
        >>> async for delta in llm_stream(messages, caller=stream_caller):
        ...     if delta.type == "text":
        ...         print(delta.text, end="", flush=True)
        ...     elif delta.type == "usage":
        ...         print(f"\\ntokens: {delta.input_tokens}+{delta.output_tokens}")
    """
    errors = _validate_messages(messages)
    if errors:
        raise LLMOprimError(f"invalid messages: {'; '.join(errors)}")

    try:
        kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        if system is not None:
            kwargs["system"] = system  # pragma: no cover

        async for raw_delta in caller(**kwargs):  # type: ignore[attr-defined]
            if not isinstance(raw_delta, dict):
                continue

            delta_type = raw_delta.get("type", "")

            if delta_type in ("text_delta", "content_block_delta"):
                yield StreamDelta(type="text", text=raw_delta.get("text", "")  # pragma: no cover
                                  or raw_delta.get("delta", {}).get("text", ""))

            elif delta_type == "text":
                yield StreamDelta(type="text", text=raw_delta.get("text", ""))

            elif delta_type == "tool_use":
                yield StreamDelta(
                    type="tool_use",
                    tool_name=raw_delta.get("name", ""),
                    tool_id=raw_delta.get("id", ""),
                    tool_input=raw_delta.get("input", {}),
                )

            elif delta_type in ("thinking", "thinking_delta"):
                yield StreamDelta(type="thinking",
                                  text=raw_delta.get("thinking", "")
                                  or raw_delta.get("text", ""))

            elif delta_type in ("usage", "message_delta"):
                usage = raw_delta.get("usage", raw_delta)
                yield StreamDelta(
                    type="usage",
                    input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
                    output_tokens=usage.get("output_tokens") or usage.get("completion_tokens") or 0,
                )

            elif delta_type in ("stop", "message_stop", "content_block_stop"):
                yield StreamDelta(
                    type="stop",
                    stop_reason=raw_delta.get("stop_reason", raw_delta.get("finish_reason", "")),
                )

    except (LLMOprimError,):
        raise  # pragma: no cover
    except Exception as e:
        raise LLMOprimError("llm_stream failed", cause=e)
