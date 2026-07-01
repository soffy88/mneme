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

def git_checkout(ref: str, *, repo: str | Path) -> None:
    """単次切换分支或还原文件到某 ref。

    Args:
        ref: 分支名、tag 或 commit hash。若需还原文件，使用 paths 参数。
        repo: Git 仓库根目录。

    Raises:
        GitOprimError: checkout 失败。

    Example:
        >>> git_checkout("main", repo="/project")
    """
    # 支持 "HEAD -- file.py" 形式，拆分为多参数
    parts = ref.split()
    _git("checkout", *parts, repo=repo)
