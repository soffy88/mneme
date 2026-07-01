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

def estimate_cost(
    in_tokens: int,
    out_tokens: int,
    *,
    model: str = "claude-sonnet-4-6",
    pricing: dict[str, float] | None = None,
) -> float:
    """估算 LLM 调用成本（USD，纯计算）。

    Args:
        in_tokens: 输入 token 数。
        out_tokens: 输出 token 数。
        model: 模型名，用于查内置价格表。
        pricing: 自定义价格 dict，格式 {"in": float, "out": float}（USD/token）；
            提供时忽略 model 价格表。

    Returns:
        估算成本（USD，float）。

    Raises:
        ParseOprimError: pricing 格式错误。

    Example:
        >>> estimate_cost(1000, 500, model="claude-sonnet-4-6")
        0.0105
    """
    try:
        if pricing is not None:
            p = pricing
        else:
            p = _DEFAULT_PRICING.get(model, _FALLBACK_PRICING)
        return in_tokens * p["in"] + out_tokens * p["out"]
    except (KeyError, TypeError) as e:  # pragma: no cover
        raise ParseOprimError("invalid pricing format", cause=e)
