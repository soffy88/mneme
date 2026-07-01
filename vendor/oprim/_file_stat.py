"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def file_stat(path: str | Path) -> dict[str, object]:
    """单次原子获取文件元数据。

    Args:
        path: 文件或目录路径。

    Returns:
        dict 含：
          - exists (bool)
          - is_file (bool)
          - is_dir (bool)
          - size (int): 字节数；若不存在为 0。
          - mtime (float): 修改时间戳；若不存在为 0.0。
          - mode (str): 八进制权限字符串，如 "0o644"。

    Raises:
        FileOprimError: stat 调用失败（权限等，非"不存在"）。

    Example:
        >>> file_stat("README.md")
        {'exists': True, 'is_file': True, 'size': 1024, ...}
    """
    p = Path(path)
    if not p.exists():
        return {
            "exists": False,
            "is_file": False,
            "is_dir": False,
            "size": 0,
            "mtime": 0.0,
            "mode": "0o000",
        }
    try:
        s = p.stat()
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot stat '{path}'", cause=e)
    return {
        "exists": True,
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "size": s.st_size,
        "mtime": s.st_mtime,
        "mode": oct(stat.S_IMODE(s.st_mode)),
    }
