"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def file_read(
    path: str | Path,
    *,
    start: int | None = None,
    end: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str:
    """单次原子读取文件内容，支持行范围切片。

    Args:
        path: 文件路径。
        start: 起始行号（0-based，含）；None 表示从头。
        end: 结束行号（0-based，不含）；None 表示到末尾。
        encoding: 文件编码，默认 utf-8。
        errors: 编码错误处理策略，默认 replace。

    Returns:
        文件内容字符串（已按行切片，若提供了 start/end）。

    Raises:
        FileOprimError: 文件不存在或读取失败。

    Example:
        >>> file_read("README.md")
        >>> file_read("src/main.py", start=0, end=20)
    """
    p = Path(path)
    try:
        text = p.read_text(encoding=encoding, errors=errors)
    except FileNotFoundError:
        raise FileOprimError(f"file not found: {path}")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read '{path}'", cause=e)

    if start is None and end is None:
        return text

    lines = text.splitlines(keepends=True)
    return "".join(lines[start:end])
