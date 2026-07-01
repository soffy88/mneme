"""oprim.lighting_control_prompt — 灯光描述注入.

Example:
    >>> from oprim.lighting_control_prompt import lighting_control_prompt
    >>> lighting_control_prompt(base_prompt="室内场景", lighting="暖")
    '室内场景, lighting: warm and cozy light'

Raises:
    ValueError: base_prompt 为空 / lighting 不在白名单.
"""

from __future__ import annotations

from typing import Literal

LightingType = Literal["暖", "冷", "戏剧", "自然", "高对比", "柔和"]

_LIGHTING_MAP: dict[str, str] = {
    "暖": "warm and cozy light",
    "冷": "cool and crisp light",
    "戏剧": "dramatic chiaroscuro lighting",
    "自然": "soft natural daylight",
    "高对比": "high contrast hard light",
    "柔和": "soft diffused light",
}

_VALID_LIGHTINGS = frozenset(_LIGHTING_MAP)


def lighting_control_prompt(
    *,
    base_prompt: str,
    lighting: LightingType,
) -> str:
    """注入灯光描述到 base_prompt.

    输出格式: '{base_prompt}, lighting: {lighting_descriptor}'

    Args:
        base_prompt: 原始 prompt，不可为空。
        lighting: 6 种灯光类型之一。

    Returns:
        注入灯光描述后的完整 prompt 字符串。

    Raises:
        ValueError: base_prompt 为空字符串 / lighting 不在白名单。

    Example:
        >>> lighting_control_prompt(base_prompt="室内场景", lighting="暖")
        '室内场景, lighting: warm and cozy light'
    """
    if not base_prompt:
        raise ValueError("base_prompt must not be empty")
    if lighting not in _VALID_LIGHTINGS:
        raise ValueError(f"Unknown lighting: {lighting!r}. Valid: {sorted(_VALID_LIGHTINGS)}")
    descriptor = _LIGHTING_MAP[lighting]
    return f"{base_prompt}, lighting: {descriptor}"


__all__ = ["lighting_control_prompt", "LightingType"]
