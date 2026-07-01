"""
oprim: 批次 B — git worktree 原子操作
======================================
包含：git_worktree_add / git_worktree_remove

归属约束
--------
✅ 每个函数 = 单次 git subprocess
✅ 失败抛 GitOprimError
✅ 互不裸调
"""

from __future__ import annotations

from pathlib import Path

from .git import _git  # 复用已有内部工具


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


def git_worktree_list(*, repo: str | Path) -> list[dict[str, str]]:
    """单次列出所有 worktree（含主 worktree）。

    Args:
        repo: Git 仓库根目录。

    Returns:
        list of {"path": str, "branch": str, "commit": str}

    Raises:
        GitOprimError: git worktree list 失败。

    Example:
        >>> git_worktree_list(repo="/project")
        [{"path": "/project", "branch": "main", "commit": "abc1234"},
         {"path": "/project-worktrees/feat", "branch": "feat", "commit": "def5678"}]
    """
    out = _git("worktree", "list", "--porcelain", repo=repo)
    worktrees = []
    current: dict[str, str] = {}

    for line in out.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:].strip(), "branch": "", "commit": ""}
        elif line.startswith("HEAD "):
            current["commit"] = line[5:].strip()[:8]
        elif line.startswith("branch "):
            branch = line[7:].strip()
            # refs/heads/main → main
            current["branch"] = branch.replace("refs/heads/", "")
        elif line == "" and current:
            continue

    if current:
        worktrees.append(current)

    return worktrees
