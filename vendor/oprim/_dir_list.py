"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def dir_list(
    path: str | Path,
    *,
    recursive: bool = False,
    include_hidden: bool = False,
) -> list[Path]:
    """单次原子列出目录内容。

    Args:
        path: 目录路径。
        recursive: 是否递归列出所有子目录内容。
        include_hidden: 是否包含以 . 开头的隐藏文件/目录。

    Returns:
        排序后的 Path 列表（相对于 path 的路径）。

    Raises:
        FileOprimError: 路径不存在或不是目录。

    Example:
        >>> dir_list("/project/src", recursive=True)
        [PosixPath('main.py'), PosixPath('utils/helper.py'), ...]
    """
    p = Path(path)
    if not p.exists():
        raise FileOprimError(f"directory not found: {path}")
    if not p.is_dir():
        raise FileOprimError(f"not a directory: {path}")

    try:
        if recursive:
            entries = [
                child.relative_to(p)
                for child in p.rglob("*")
                if include_hidden or not any(
                    part.startswith(".") for part in child.relative_to(p).parts
                )
            ]
        else:
            entries = [
                child.relative_to(p)
                for child in p.iterdir()
                if include_hidden or not child.name.startswith(".")
            ]
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot list '{path}'", cause=e)

    return sorted(entries)
