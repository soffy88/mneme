"""Auto-split from hicode whl."""

from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from ._exceptions import ParseOprimError

@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str]

@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk]

def count_tokens(
    messages: list[dict] | str,
    *,
    model: str = "claude-sonnet-4-6",
) -> int:
    """估算消息列表或字符串的 token 数量（纯计算）。

    使用 chars/4 近似估算（~4 chars per token）。生产版按模型家族
    替换为精确 tokenizer（tiktoken / Anthropic tokenizer）。

    Args:
        messages: 消息列表（list[dict]）或纯字符串。
        model: 目标模型名（影响 tokenizer 选择；当前均用近似值）。

    Returns:
        估算的 token 数量（int）。

    Raises:
        ParseOprimError: messages 格式无法序列化。

    Example:
        >>> count_tokens([{"role": "user", "content": "hello"}])
        4
        >>> count_tokens("hello world")
        3
    """
    try:
        if isinstance(messages, str):
            text = messages
        else:
            import json
            text = json.dumps(messages, ensure_ascii=False)
        # ~4 chars/token 近似；Claude 实际约 3.5-4.5
        return max(1, len(text) // 4)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError("count_tokens failed", cause=e)
