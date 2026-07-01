"""Auto-split from hicode whl."""

from __future__ import annotations
from pathlib import Path
from .git import _git

def git_worktree_add(
    branch: str,
    *,
    repo: str | Path,
    path: str | Path | None = None,
    create_branch: bool = True,
) -> Path:
    """单次添加 git worktree，返回 worktree 目录路径。

    用途：为并行 subagent 提供隔离的工作目录，各自在独立文件树上操作，
    不影响主工作区。

    Args:
        branch: worktree 对应的分支名。
        repo: Git 仓库根目录。
        path: worktree 目录路径；None 时自动在 repo 同级创建
            "<repo>-worktrees/<branch>" 目录。
        create_branch: True 时若分支不存在则创建（-b 参数）；
            False 时分支必须已存在。

    Returns:
        worktree 目录的绝对 Path。

    Raises:
        GitOprimError: git worktree add 失败。

    Example:
        >>> wt = git_worktree_add("feat/parallel", repo="/project")
        >>> wt
        PosixPath('/project-worktrees/feat-parallel')
    """
    repo_path = Path(repo).resolve()

    if path is None:
        # 自动路径：repo 同级的 <name>-worktrees/<branch-safe>
        branch_safe = branch.replace("/", "-").replace(" ", "_")
        wt_path = repo_path.parent / f"{repo_path.name}-worktrees" / branch_safe
    else:
        wt_path = Path(path).resolve()

    wt_path.parent.mkdir(parents=True, exist_ok=True)

    args = ["worktree", "add"]
    if create_branch:
        args.extend(["-b", branch])
    args.append(str(wt_path))
    if not create_branch:
        args.append(branch)  # pragma: no cover

    _git(*args, repo=repo_path)
    return wt_path
