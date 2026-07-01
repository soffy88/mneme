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

def git_show(ref: str, *, repo: str | Path, path: str | None = None) -> str:
    """单次查看 commit 内容或特定文件在某 ref 的内容。

    Args:
        ref: commit hash / tag / branch。
        repo: Git 仓库根目录。
        path: 若提供，显示该文件在 ref 的内容（git show ref:path）。

    Returns:
        git show 输出字符串。

    Raises:
        GitOprimError: ref 不存在或操作失败。

    Example:
        >>> git_show("HEAD", repo="/project")
        >>> git_show("HEAD", repo="/project", path="src/main.py")
    """
    if path:
        return _git("show", f"{ref}:{path}", repo=repo)
    return _git("show", ref, repo=repo)
