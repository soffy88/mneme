"""Auto-split from hicode whl."""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from ._exceptions import OprimError
from ._protocols import PersistenceHandle
from .text import count_tokens

class PromptOprimError(OprimError):
    """prompt 构建 / 消息处理失败。"""

class SnapshotOprimError(OprimError):
    """会话快照失败。"""

@dataclass
class ThinkingResult:
    """扩展思考提取结果。"""
    thinking: str
    text: str
    has_thinking: bool
    thinking_blocks: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)

@dataclass
class ConversationSnapshot:
    """会话快照结构。"""
    snapshot_id: str
    session_id: str
    message_count: int
    created_at: float
    store_key: str
    revision: str

def extract_thinking(response: dict) -> ThinkingResult:
    """从 LLM 响应中拆分 thinking block 和 text block（纯计算）。

    支持 Anthropic 扩展思考格式（interleaved thinking）。
    response 是 caller 返回的原始 dict 或 LLMResponse.raw。

    Args:
        response: LLM 原始响应 dict（含 content 列表）。

    Returns:
        ThinkingResult(thinking, text, has_thinking, thinking_blocks, text_blocks)。

    Raises:
        PromptOprimError: response 格式无法解析。

    Example:
        >>> result = extract_thinking(raw_response)
        >>> result.has_thinking
        True
        >>> result.thinking[:50]
        "Let me think about this step by step..."
    """
    content = response.get("content", [])
    if not isinstance(content, list):
        if isinstance(content, str):
            return ThinkingResult(
                thinking="", text=content,
                has_thinking=False, text_blocks=[content],
            )
        raise PromptOprimError(
            f"extract_thinking: content must be list or str, got {type(content).__name__}"
        )

    thinking_blocks: list[str] = []
    text_blocks: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            continue  # pragma: no cover
        btype = block.get("type", "")
        if btype == "thinking":
            thinking_blocks.append(block.get("thinking", ""))
        elif btype == "text":
            text_blocks.append(block.get("text", ""))
        # tool_use 和其他 block 忽略

    return ThinkingResult(
        thinking="\n\n".join(thinking_blocks),
        text="\n".join(text_blocks),
        has_thinking=bool(thinking_blocks),
        thinking_blocks=thinking_blocks,
        text_blocks=text_blocks,
    )
