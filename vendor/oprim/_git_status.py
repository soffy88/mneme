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

def git_status(*, repo: str | Path) -> list[FileStatus]:
    """单次获取工作区状态（porcelain v1）。

    Args:
        repo: Git 仓库根目录。

    Returns:
        FileStatus 列表，每项含 path / index / worktree 状态字符。

    Raises:
        GitOprimError: git 命令失败或 repo 不是 git 仓库。

    Example:
        >>> git_status(repo="/project")
        [FileStatus(path='src/main.py', index='M', worktree=' '), ...]
    """
    out = _git("status", "--porcelain=v1", "-u", repo=repo)
    statuses = []
    for line in out.splitlines():
        if not line:  # pragma: no cover
            continue
        index = line[0]
        worktree = line[1]
        rest = line[3:]
        renamed_from = None
        if " -> " in rest:
            renamed_from, rest = rest.split(" -> ", 1)
        statuses.append(FileStatus(
            path=rest.strip(),
            index=index,
            worktree=worktree,
            renamed_from=renamed_from,
        ))
    return statuses
