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

def git_stash(*, repo: str | Path, pop: bool = False, message: str = "") -> str:
    """单次 stash 操作（push 或 pop）。

    Args:
        repo: Git 仓库根目录。
        pop: True 时执行 stash pop，False 时执行 stash push。
        message: stash push 时的描述（可选）。

    Returns:
        git stash 输出字符串。

    Raises:
        GitOprimError: stash 操作失败。

    Example:
        >>> git_stash(repo="/project")              # push
        >>> git_stash(repo="/project", pop=True)   # pop
    """
    if pop:
        return _git("stash", "pop", repo=repo).strip()
    args = ["stash", "push"]
    if message:
        args.extend(["-m", message])
    return _git(*args, repo=repo).strip()
