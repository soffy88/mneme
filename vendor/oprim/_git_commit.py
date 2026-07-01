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

def git_commit(*, repo: str | Path, message: str, allow_empty: bool = False) -> str:
    """单次创建 commit，返回 commit hash。

    Args:
        repo: Git 仓库根目录。
        message: commit 消息。
        allow_empty: 允许空 commit，默认 False。

    Returns:
        commit SHA（短 hash，8位）。

    Raises:
        GitOprimError: git commit 失败（如暂存区为空且 allow_empty=False）。

    Example:
        >>> git_commit(repo="/project", message="feat: add login")
        'a1b2c3d4'
    """
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _git(*args, repo=repo)
    # 取最新 commit hash
    return _git("rev-parse", "--short=8", "HEAD", repo=repo).strip()
