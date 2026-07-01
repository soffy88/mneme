"""Auto-split from hicode whl."""

from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path
from ._exceptions import GitOprimError

@dataclass
class FileStatus:
    path: str
    index: str
    worktree: str
    renamed_from: str | None = None

@dataclass
class Commit:
    hash: str
    author: str
    date: str
    message: str

@dataclass
class BlameLine:
    lineno: int
    commit: str
    author: str
    content: str

def git_diff(
    *,
    repo: str | Path,
    staged: bool = False,
    paths: list[str] | None = None,
    context_lines: int = 3,
) -> str:
    """单次获取 diff 输出（unified format）。

    Args:
        repo: Git 仓库根目录。
        staged: True 时获取暂存区 diff（--cached）。
        paths: 限定 diff 的文件列表；None 表示全部。
        context_lines: 上下文行数，默认 3。

    Returns:
        unified diff 字符串。

    Raises:
        GitOprimError: git diff 失败。

    Example:
        >>> git_diff(repo="/project", staged=True)
    """
    args = ["diff", f"-U{context_lines}"]
    if staged:
        args.append("--cached")
    if paths:
        args.extend(["--", *paths])
    return _git(*args, repo=repo)
