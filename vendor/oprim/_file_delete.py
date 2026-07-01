"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def file_delete(path: str | Path, *, missing_ok: bool = False) -> bool:
    """单次原子删除文件（不删目录）。

    Args:
        path: 文件路径。
        missing_ok: True 时文件不存在不抛异常，返回 False。

    Returns:
        True 表示成功删除；False 表示文件不存在（仅 missing_ok=True 时）。

    Raises:
        FileOprimError: 文件不存在（missing_ok=False）或删除失败。

    Example:
        >>> file_delete("/tmp/old.py")
        True
        >>> file_delete("/tmp/nonexist.py", missing_ok=True)
        False
    """
    p = Path(path)
    existed = p.exists()
    try:
        p.unlink(missing_ok=missing_ok)
    except FileNotFoundError:
        raise FileOprimError(f"file not found: {path}")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot delete '{path}'", cause=e)
    return existed  # True if the file existed and was deleted
