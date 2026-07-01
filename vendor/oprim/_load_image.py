"""Auto-split from hicode whl."""

from __future__ import annotations
import asyncio
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from ._exceptions import FileOprimError, ParseOprimError, ShellOprimError

@dataclass
class HookResult:
    decision: str
    output: str
    exit_code: int

@dataclass
class ImageBlock:
    """Anthropic content block 格式的图片表示。"""
    type: str
    source_type: str
    media_type: str
    data: str
    path: str
    size_bytes: int

@dataclass
class SkillMeta:
    """Skill frontmatter 解析结果（渐进披露第 1 步，不含 body）。"""
    name: str
    description: str
    version: str
    tools: list[str]
    hooks: list[dict]
    tags: list[str]
    raw: dict
    skill_dir: str

def load_image(path: str | Path) -> ImageBlock:
    """单次读取图片文件，返回 base64 编码的 content block。

    用于构造多模态 LLM 请求的图片输入。

    Args:
        path: 图片文件路径（支持 jpg/jpeg/png/gif/webp/bmp/svg）。

    Returns:
        ImageBlock，可直接用于 Anthropic messages content 数组。

    Raises:
        FileOprimError: 文件不存在或读取失败。
        ParseOprimError: 不支持的图片格式。

    Example:
        >>> block = load_image("screenshot.png")
        >>> block.media_type
        'image/png'
        >>> # 用于 LLM 消息
        >>> content = [{"type": "image", "source": {
        ...     "type": "base64",
        ...     "media_type": block.media_type,
        ...     "data": block.data,
        ... }}]
    """
    p = Path(path)
    if not p.exists():
        raise FileOprimError(f"image file not found: {path}")

    ext = p.suffix.lower()
    if ext not in _IMAGE_MIME:
        raise ParseOprimError(
            f"unsupported image format '{ext}': "
            f"supported: {', '.join(_IMAGE_MIME)}"
        )

    try:
        raw = p.read_bytes()
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read image '{path}'", cause=e)

    return ImageBlock(
        type="image",
        source_type="base64",
        media_type=_IMAGE_MIME[ext],
        data=base64.standard_b64encode(raw).decode("ascii"),
        path=str(p),
        size_bytes=len(raw),
    )
