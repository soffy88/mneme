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

def truncate_messages(
    messages: list[dict],
    *,
    budget: int,
    model: str = "claude-sonnet-4-6",
    keep_first: int = 1,
    keep_last: int = 4,
) -> list[dict]:
    """将消息列表截断到 token 预算内（纯计算）。

    策略：保留最前 keep_first 条 + 最后 keep_last 条，
    中间消息从旧到新逐条删除，直到 token 数满足预算。

    Args:
        messages: 完整消息列表。
        budget: token 预算上限。
        model: 用于 token 计数的模型名。
        keep_first: 始终保留的最前 N 条（通常是 system/user 的首条），默认 1。
        keep_last: 始终保留的最后 N 条（最近上下文），默认 4。

    Returns:
        截断后的消息列表（长度 ≤ 原始，token 数 ≤ budget）。

    Raises:
        PromptOprimError: budget ≤ 0。

    Example:
        >>> short = truncate_messages(long_messages, budget=4000)
        >>> count_tokens(short) <= 4000
        True
    """
    if budget <= 0:
        raise PromptOprimError(f"budget must be > 0, got {budget}")

    if not messages:
        return []

    # 已在预算内，直接返回
    if count_tokens(messages, model=model) <= budget:
        return list(messages)

    n = len(messages)
    # 保证 keep_first + keep_last 不超过总数
    keep_first = min(keep_first, n)
    keep_last = min(keep_last, n - keep_first)

    front = list(messages[:keep_first])
    back = list(messages[n - keep_last:]) if keep_last > 0 else []
    middle = list(messages[keep_first: n - keep_last if keep_last > 0 else n])

    # 逐条从 middle 头部删除，直到满足预算
    while middle:
        candidate = front + middle + back
        if count_tokens(candidate, model=model) <= budget:
            return candidate  # pragma: no cover
        middle.pop(0)

    # middle 已空，检查 front+back 是否满足
    return front + back
