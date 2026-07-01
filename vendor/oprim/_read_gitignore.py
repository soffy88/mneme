"""Auto-split from hicode whl."""

from __future__ import annotations
import stat
from pathlib import Path
from ._exceptions import FileOprimError, PathSecurityError

def read_gitignore(root: str | Path) -> list[str]:
    """单次读取并解析 .gitignore 文件，返回规则列表。

    不存在时返回空列表（不抛异常）。注释行和空行被过滤。

    Args:
        root: 包含 .gitignore 的目录路径。

    Returns:
        gitignore 规则字符串列表（保留原始格式，不解析 negation）。

    Raises:
        FileOprimError: .gitignore 存在但读取失败。

    Example:
        >>> read_gitignore("/project")
        ['*.pyc', '__pycache__/', '.env', ...]
    """
    gitignore = Path(root) / ".gitignore"
    if not gitignore.exists():
        return []
    try:
        text = gitignore.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read .gitignore in '{root}'", cause=e)

    rules = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rules.append(stripped)
    return rules
