"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def glob_match(
    pattern: str,
    *,
    root: str | Path,
    respect_gitignore: bool = True,
) -> list[Path]:
    """单次原子 glob 匹配，返回匹配文件列表。

    Args:
        pattern: glob 模式，如 "**/*.py" 或 "src/*.ts"。
        root: 搜索根目录。
        respect_gitignore: 若 True，过滤掉 .gitignore 中匹配的路径（简化实现：
            过滤 .git/ 目录及以 . 开头的目录）。

    Returns:
        排序后的绝对 Path 列表。

    Raises:
        FileOprimError: root 不存在或不是目录。

    Example:
        >>> glob_match("**/*.py", root="/project", respect_gitignore=True)
        [PosixPath('/project/src/main.py'), ...]
    """
    r = Path(root)
    if not r.exists():
        raise FileOprimError(f"root not found: {root}")
    if not r.is_dir():
        raise FileOprimError(f"root is not a directory: {root}")

    try:
        matches = list(r.glob(pattern))
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"glob failed for '{pattern}' in '{root}'", cause=e)

    if respect_gitignore:
        matches = [
            p for p in matches
            if ".git" not in p.parts
            and not any(part.startswith(".") for part in p.relative_to(r).parts)
        ]

    return sorted(matches)
