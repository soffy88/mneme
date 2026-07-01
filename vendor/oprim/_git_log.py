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

def git_log(*, repo: str | Path, n: int = 20, path: str | None = None) -> list[Commit]:
    """单次获取 commit 历史。

    Args:
        repo: Git 仓库根目录。
        n: 最多返回条数，默认 20。
        path: 限定文件路径的历史；None 表示整个 repo。

    Returns:
        Commit 列表（最新在前）。

    Raises:
        GitOprimError: git log 失败。

    Example:
        >>> git_log(repo="/project", n=5)
    """
    sep = "|||"
    fmt = f"%H{sep}%an{sep}%ai{sep}%s"
    args = ["log", f"-{n}", f"--pretty=format:{fmt}"]
    if path:
        args.extend(["--", path])
    out = _git(*args, repo=repo)
    commits = []
    for line in out.splitlines():
        if not line:  # pragma: no cover
            continue
        parts = line.split(sep)
        if len(parts) >= 4:
            commits.append(Commit(
                hash=parts[0],
                author=parts[1],
                date=parts[2],
                message=parts[3],
            ))
    return commits
