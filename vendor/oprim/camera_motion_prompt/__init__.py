"""oprim.camera_motion_prompt — 视频生成镜头运动 prompt 生成.

Example:
    >>> from oprim.camera_motion_prompt import camera_motion_prompt
    >>> camera_motion_prompt(base_motion=None, motion_type="pan_left", intensity=0.2)
    'camera pans left, slow motion'
    >>> camera_motion_prompt(base_motion="forest scene", motion_type="dolly_in", intensity=0.5)
    'forest scene, camera moves forward (dolly in), medium motion'

Raises:
    ValueError: intensity 不在 [0,1] / motion_type 不在白名单.
"""

from __future__ import annotations

from typing import Literal

MotionType = Literal[
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "dolly_in",
    "dolly_out",
    "rotate",
    "static",
]

_MOTION_MAP: dict[str, str] = {
    "pan_left": "camera pans left",
    "pan_right": "camera pans right",
    "tilt_up": "camera tilts up",
    "tilt_down": "camera tilts down",
    "dolly_in": "camera moves forward (dolly in)",
    "dolly_out": "camera pulls back (dolly out)",
    "rotate": "camera rotates around subject",
    "static": "static locked-off shot",
}

_VALID_MOTIONS = frozenset(_MOTION_MAP)


def _intensity_word(intensity: float) -> str:
    if intensity <= 0.33:
        return "slow"
    if intensity <= 0.67:
        return "medium"
    return "fast"


def camera_motion_prompt(
    *,
    base_motion: str | None,
    motion_type: MotionType,
    intensity: float = 0.5,
) -> str:
    """生成视频生成镜头运动 prompt.

    intensity 映射:
      [0.0, 0.33] → "slow"
      (0.33, 0.67] → "medium"
      (0.67, 1.0]  → "fast"

    输出格式:
      base_motion=None  → '{motion_descriptor}, {intensity_word} motion'
      base_motion 非空  → '{base_motion}, {motion_descriptor}, {intensity_word} motion'

    Args:
        base_motion: 已有 motion 描述，可为 None。
        motion_type: 8 种镜头运动类型之一。
        intensity: 运动强度，[0, 1]。默认 0.5。

    Returns:
        完整镜头运动 prompt 字符串。

    Raises:
        ValueError: intensity 不在 [0, 1] / motion_type 不在白名单。

    Example:
        >>> camera_motion_prompt(base_motion=None, motion_type="pan_left", intensity=0.2)
        'camera pans left, slow motion'
    """
    if not 0.0 <= intensity <= 1.0:
        raise ValueError(f"intensity must be in [0, 1], got {intensity}")
    if motion_type not in _VALID_MOTIONS:
        raise ValueError(f"Unknown motion_type: {motion_type!r}. Valid: {sorted(_VALID_MOTIONS)}")
    motion_desc = _MOTION_MAP[motion_type]
    iword = _intensity_word(intensity)
    if base_motion:
        return f"{base_motion}, {motion_desc}, {iword} motion"
    return f"{motion_desc}, {iword} motion"


__all__ = ["camera_motion_prompt", "MotionType"]
