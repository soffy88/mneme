"""oprim.video_edit_element_remove — 视频精准编辑去除元素.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.video_edit_element_remove import video_edit_element_remove
    >>> result = asyncio.run(video_edit_element_remove(
    ...     video_path=Path("input.mp4"),
    ...     element_mask=Path("mask.png"),
    ...     inpaint_provider="sam2_inpaint",
    ...     output_path=Path("output.mp4"),
    ... ))

Raises:
    FileNotFoundError: video_path 不存在.
    VideoEditError: provider 失败.
"""

from __future__ import annotations

from pathlib import Path

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class VideoEditError(Exception):
    """视频编辑失败."""


class VideoEditProviderNotFoundError(VideoEditError):
    """Provider not registered."""


async def video_edit_element_remove(
    *,
    video_path: Path,
    element_mask: Path | str,
    inpaint_provider: str,
    output_path: Path,
    timeout_s: float = 600.0,
) -> Path:
    """视频精准编辑去除元素.

    通过 ProviderRegistry.get(category='video_inpaint', name=inpaint_provider)
    获取 inpaint provider，去除视频中指定区域/元素。

    Args:
        video_path: 输入视频路径。
        element_mask: 掩码图片路径（Path）或文字描述（str）。
        inpaint_provider: Inpaint provider 名称（category='video_inpaint'）。
        output_path: 输出视频文件路径。
        timeout_s: 超时时间（秒），默认 600。

    Returns:
        output_path on success.

    Raises:
        FileNotFoundError: video_path 文件不存在。
        VideoEditProviderNotFoundError: Provider 未注册。
        VideoEditError: Provider 调用失败或输出文件未生成。

    Example:
        >>> result = await video_edit_element_remove(
        ...     video_path=Path("in.mp4"), element_mask=Path("mask.png"),
        ...     inpaint_provider="sam2_inpaint", output_path=Path("out.mp4"),
        ... )
    """
    if not video_path.exists():
        raise FileNotFoundError(f"video_path not found: {video_path}")

    try:
        fn = ProviderRegistry.get().generic("video_inpaint", inpaint_provider)
    except ProviderNotFoundError as exc:
        raise VideoEditProviderNotFoundError(
            f"Inpaint provider not found: {inpaint_provider!r}"
        ) from exc

    try:
        await fn(
            video_path=video_path,
            mask=element_mask,
            output_path=output_path,
            timeout_s=timeout_s,
        )
    except (VideoEditError, VideoEditProviderNotFoundError):
        raise
    except Exception as exc:
        raise VideoEditError(f"Video edit failed: {exc}") from exc

    if not output_path.exists():
        raise VideoEditError(f"Provider did not produce output: {output_path}")
    return output_path


__all__ = [
    "video_edit_element_remove",
    "VideoEditError",
    "VideoEditProviderNotFoundError",
]
