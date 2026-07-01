"""oprim.first_last_frame_transition — 首尾帧自动过渡视频生成.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.first_last_frame_transition import first_last_frame_transition
    >>> result = asyncio.run(first_last_frame_transition(
    ...     first_frame=Path("start.png"), last_frame=Path("end.png"),
    ...     duration_s=3.0, video_provider="wan22_local",
    ...     output_path=Path("transition.mp4"),
    ... ))

Raises:
    FileNotFoundError: 输入帧文件不存在.
    FrameTransitionError: provider 失败 / timeout / 输出文件未生成.
"""

from __future__ import annotations

from pathlib import Path

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class FrameTransitionError(Exception):
    """首尾帧过渡视频生成失败."""


class FrameTransitionProviderNotFoundError(FrameTransitionError):
    """Provider not registered."""


async def first_last_frame_transition(
    *,
    first_frame: Path,
    last_frame: Path,
    duration_s: float,
    video_provider: str,
    output_path: Path,
    timeout_s: float = 600.0,
) -> Path:
    """首尾帧 → 自动过渡视频.

    通过 ProviderRegistry.get(category='image_to_video', name=video_provider)
    获取 provider callable，生成从 first_frame 到 last_frame 的过渡视频。

    Args:
        first_frame: 起始帧图片路径。
        last_frame: 结束帧图片路径。
        duration_s: 过渡视频时长（秒）。
        video_provider: Provider 名称（category='image_to_video'）。
        output_path: 输出视频文件路径。
        timeout_s: 超时时间（秒），默认 600。

    Returns:
        output_path on success.

    Raises:
        FileNotFoundError: first_frame 或 last_frame 文件不存在。
        FrameTransitionProviderNotFoundError: Provider 未注册。
        FrameTransitionError: Provider 调用失败或输出文件未生成。

    Example:
        >>> result = await first_last_frame_transition(
        ...     first_frame=Path("start.png"), last_frame=Path("end.png"),
        ...     duration_s=3.0, video_provider="wan22_local",
        ...     output_path=Path("transition.mp4"),
        ... )
    """
    if not first_frame.exists():
        raise FileNotFoundError(f"first_frame not found: {first_frame}")
    if not last_frame.exists():
        raise FileNotFoundError(f"last_frame not found: {last_frame}")

    try:
        fn = ProviderRegistry.get().generic("image_to_video", video_provider)
    except ProviderNotFoundError as exc:
        raise FrameTransitionProviderNotFoundError(
            f"Video provider not found: {video_provider!r}"
        ) from exc

    try:
        await fn(
            first_frame=first_frame,
            last_frame=last_frame,
            duration_s=duration_s,
            output_path=output_path,
            timeout_s=timeout_s,
        )
    except (FrameTransitionError, FrameTransitionProviderNotFoundError):
        raise
    except Exception as exc:
        raise FrameTransitionError(f"Transition generation failed: {exc}") from exc

    if not output_path.exists():
        raise FrameTransitionError(f"Provider did not produce output: {output_path}")
    return output_path


__all__ = [
    "first_last_frame_transition",
    "FrameTransitionError",
    "FrameTransitionProviderNotFoundError",
]
