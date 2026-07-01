"""Auto-split from hicode whl."""

from __future__ import annotations
from pathlib import Path
from .git import _git

def git_worktree_remove(
    path: str | Path,
    *,
    repo: str | Path,
    force: bool = False,
) -> None:
    """单次移除 git worktree。

    Args:
        path: worktree 目录路径（git worktree add 返回的路径）。
        repo: Git 仓库根目录。
        force: True 时即使 worktree 有未提交修改也强制移除。

    Raises:
        GitOprimError: git worktree remove 失败。

    Example:
        >>> git_worktree_remove("/project-worktrees/feat-parallel", repo="/project")
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(Path(path).resolve()))

    _git(*args, repo=repo)
