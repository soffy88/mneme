"""oprim.style_marker_prompt — 风格关键词注入.

Example:
    >>> from oprim.style_marker_prompt import style_marker_prompt
    >>> style_marker_prompt(base_prompt="一只猫", style="治愈")
    '一只猫, 治愈风格, 温暖柔和'

Raises:
    ValueError: base_prompt 为空 / style 不在白名单.
"""

from __future__ import annotations

from typing import Literal

StyleType = Literal["科普", "严肃", "搞笑", "治愈", "悬疑", "热血", "温暖"]

_STYLE_MAP: dict[str, tuple[str, str]] = {
    "科普": ("科普风格", "通俗易懂"),
    "严肃": ("严肃风格", "庄重权威"),
    "搞笑": ("搞笑风格", "轻松幽默"),
    "治愈": ("治愈风格", "温暖柔和"),
    "悬疑": ("悬疑风格", "紧张神秘"),
    "热血": ("热血风格", "激昂澎湃"),
    "温暖": ("温暖风格", "亲切温馨"),
}

_VALID_STYLES = frozenset(_STYLE_MAP)


def style_marker_prompt(
    *,
    base_prompt: str,
    style: StyleType,
) -> str:
    """注入风格关键词 + 调性描述到 base_prompt.

    输出格式: '{base_prompt}, {style_keywords}, {tone_descriptor}'

    Args:
        base_prompt: 原始 prompt，不可为空。
        style: 7 种风格之一。

    Returns:
        注入风格后的完整 prompt 字符串。

    Raises:
        ValueError: base_prompt 为空字符串 / style 不在白名单。

    Example:
        >>> style_marker_prompt(base_prompt="一只猫", style="治愈")
        '一只猫, 治愈风格, 温暖柔和'
    """
    if not base_prompt:
        raise ValueError("base_prompt must not be empty")
    if style not in _VALID_STYLES:
        raise ValueError(f"Unknown style: {style!r}. Valid: {sorted(_VALID_STYLES)}")
    keywords, tone = _STYLE_MAP[style]
    return f"{base_prompt}, {keywords}, {tone}"


__all__ = ["style_marker_prompt", "StyleType"]
