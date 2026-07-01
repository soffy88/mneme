"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def file_write(
    path: str | Path,
    *,
    content: str,
    encoding: str = "utf-8",
    mkdirs: bool = True,
) -> Path:
    """单次原子写入文件（覆盖）。

    Args:
        path: 目标文件路径。
        content: 写入内容。
        encoding: 编码，默认 utf-8。
        mkdirs: 若父目录不存在是否自动创建，默认 True。

    Returns:
        写入完成的 Path 对象。

    Raises:
        FileOprimError: 写入失败。

    Example:
        >>> file_write("/tmp/out.py", content="x = 1\n")
    """
    p = Path(path)
    try:
        if mkdirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot write '{path}'", cause=e)
    return p
