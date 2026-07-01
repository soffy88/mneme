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

def compute_diff(
    old: str,
    new: str,
    *,
    path: str = "",
    context_lines: int = 3,
) -> str:
    """计算两个字符串之间的 unified diff。

    Args:
        old: 原始内容。
        new: 新内容。
        path: 显示在 diff header 里的文件路径（可选）。
        context_lines: 上下文行数，默认 3。

    Returns:
        unified diff 字符串；若内容相同返回空字符串。

    Raises:
        ParseOprimError: 生成 diff 失败（极少见）。

    Example:
        >>> compute_diff("a\nb\n", "a\nc\n", path="file.py")
        '--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n'
    """
    try:
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        label_a = f"a/{path}" if path else "original"
        label_b = f"b/{path}" if path else "modified"
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=label_a, tofile=label_b,
            n=context_lines,
        )
        return "".join(diff)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError("failed to compute diff", cause=e)
