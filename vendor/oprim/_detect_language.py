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

def detect_language(
    path: str | Path,
    *,
    content: str | None = None,
) -> str:
    """根据文件路径（和可选内容）检测编程语言。

    Args:
        path: 文件路径（使用扩展名和文件名判断）。
        content: 文件内容（可选，用于 shebang 检测）。

    Returns:
        小写语言标识字符串，如 "python" / "typescript" / "unknown"。

    Raises:
        ParseOprimError: 路径解析失败。

    Example:
        >>> detect_language("src/main.py")
        'python'
        >>> detect_language("Dockerfile")
        'dockerfile'
    """
    try:
        p = Path(path)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError(f"invalid path: {path}", cause=e)

    # 精确文件名匹配
    if p.name in _FILENAME_MAP:
        return _FILENAME_MAP[p.name]

    # 扩展名匹配
    ext = p.suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]

    # shebang 检测
    if content:
        first_line = content.splitlines()[0] if content.strip() else ""
        if first_line.startswith("#!"):
            if "python" in first_line:
                return "python"
            if "node" in first_line or "deno" in first_line:
                return "javascript"
            if "bash" in first_line:
                return "bash"
            if "sh" in first_line:
                return "shell"

    return "unknown"
