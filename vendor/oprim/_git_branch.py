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

def git_branch(
    *,
    repo: str | Path,
    name: str | None = None,
    create: bool = False,
    delete: bool = False,
) -> list[str] | str:
    """单次分支操作：列出 / 创建 / 删除分支。

    Args:
        repo: Git 仓库根目录。
        name: 分支名；None 时为列出所有分支。
        create: True 时创建分支（需提供 name）。
        delete: True 时删除分支（需提供 name）。

    Returns:
        列出时返回分支名列表（当前分支有 * 前缀已去除）；
        创建/删除时返回操作信息字符串。

    Raises:
        GitOprimError: 操作失败。

    Example:
        >>> git_branch(repo="/project")                     # 列出
        >>> git_branch(repo="/project", name="feat", create=True)  # 创建
    """
    if create and name:
        return _git("checkout", "-b", name, repo=repo).strip()
    if delete and name:
        return _git("branch", "-d", name, repo=repo).strip()
    # 列出
    out = _git("branch", "--list", repo=repo)
    return [line.strip().lstrip("* ") for line in out.splitlines() if line.strip()]
