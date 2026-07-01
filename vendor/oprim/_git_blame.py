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

def git_blame(path: str, *, repo: str | Path) -> list[BlameLine]:
    """单次获取文件的 blame 信息（每行对应的 commit/author）。

    Args:
        path: 相对于 repo root 的文件路径。
        repo: Git 仓库根目录。

    Returns:
        BlameLine 列表，每项含行号、commit hash、作者、内容。

    Raises:
        GitOprimError: git blame 失败。

    Example:
        >>> git_blame("src/main.py", repo="/project")
    """
    out = _git(
        "blame", "--porcelain", path,
        repo=repo,
    )
    lines: list[BlameLine] = []
    current_commit = ""
    current_author = ""
    lineno = 0

    for line in out.splitlines():
        # 行首 40 hex chars = commit hash 行
        if len(line) >= 40 and all(c in "0123456789abcdef" for c in line[:40]) and line[40] == " ":
            parts = line.split()
            current_commit = parts[0]
            lineno = int(parts[2])
        elif line.startswith("author "):
            current_author = line[7:]
        elif line.startswith("\t"):
            lines.append(BlameLine(
                lineno=lineno,
                commit=current_commit[:8],
                author=current_author,
                content=line[1:],
            ))
    return lines
