"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def path_resolve(
    path: str | Path,
    *,
    sandbox_root: str | Path | None = None,
) -> Path:
    """解析路径为绝对路径，可选沙箱越界校验。

    Args:
        path: 待解析的路径（相对或绝对）。
        sandbox_root: 若提供，校验 resolved 路径在此目录内；越界抛
            PathSecurityError。

    Returns:
        解析后的 Path 对象（绝对路径）。

    Raises:
        PathSecurityError: 路径超出 sandbox_root 范围。

    Example:
        >>> path_resolve("src/main.py", sandbox_root="/project")
        PosixPath('/project/src/main.py')  # 视 cwd 而定
    """
    resolved = Path(path).resolve()
    if sandbox_root is not None:
        root = Path(sandbox_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PathSecurityError(
                f"path '{resolved}' is outside sandbox root '{root}'"
            )
    return resolved
