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

def git_add(paths: list[str] | str, *, repo: str | Path) -> None:
    """单次将文件加入暂存区。

    Args:
        paths: 单个路径字符串或路径列表。
        repo: Git 仓库根目录。

    Raises:
        GitOprimError: git add 失败。

    Example:
        >>> git_add(["src/main.py", "tests/test_main.py"], repo="/project")
    """
    if isinstance(paths, str):
        paths = [paths]
    _git("add", "--", *paths, repo=repo)
