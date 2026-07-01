"""Auto-split from hicode whl."""

from __future__ import annotations
from pathlib import Path
from .git import _git

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
