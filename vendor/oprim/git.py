"""
oprim: Git 原子操作集
=====================
包含：git_status / git_diff / git_add / git_commit / git_log
      git_branch / git_checkout / git_stash / git_show / git_blame

归属约束
--------
✅ 每个函数 = 单次 subprocess 调用
✅ ≤1 个核心位置参数，其余 keyword-only
✅ 失败抛 GitOprimError
✅ oprim 之间不裸调
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ._exceptions import GitOprimError


# ---------------------------------------------------------------------------
# 内部工具（不暴露为 oprim）
# ---------------------------------------------------------------------------

def _git(
    *args: str,
    repo: str | Path,
    input_text: str | None = None,
) -> str:
    """运行 git 命令，返回 stdout 字符串；失败抛 GitOprimError。"""
    cmd = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=60,
        )
    except FileNotFoundError:  # pragma: no cover
        raise GitOprimError("git executable not found")
    except subprocess.TimeoutExpired:  # pragma: no cover
        raise GitOprimError(f"git command timed out: {' '.join(args)}")

    if result.returncode != 0:
        raise GitOprimError(
            f"git {args[0]} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------

@dataclass
class FileStatus:
    path: str
    index: str   # staged status char
    worktree: str  # worktree status char
    renamed_from: str | None = None


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


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------

def git_diff(
    *,
    repo: str | Path,
    staged: bool = False,
    paths: list[str] | None = None,
    context_lines: int = 3,
) -> str:
    """单次获取 diff 输出（unified format）。

    Args:
        repo: Git 仓库根目录。
        staged: True 时获取暂存区 diff（--cached）。
        paths: 限定 diff 的文件列表；None 表示全部。
        context_lines: 上下文行数，默认 3。

    Returns:
        unified diff 字符串。

    Raises:
        GitOprimError: git diff 失败。

    Example:
        >>> git_diff(repo="/project", staged=True)
    """
    args = ["diff", f"-U{context_lines}"]
    if staged:
        args.append("--cached")
    if paths:
        args.extend(["--", *paths])
    return _git(*args, repo=repo)


# ---------------------------------------------------------------------------
# git_add
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------

def git_commit(*, repo: str | Path, message: str, allow_empty: bool = False) -> str:
    """单次创建 commit，返回 commit hash。

    Args:
        repo: Git 仓库根目录。
        message: commit 消息。
        allow_empty: 允许空 commit，默认 False。

    Returns:
        commit SHA（短 hash，8位）。

    Raises:
        GitOprimError: git commit 失败（如暂存区为空且 allow_empty=False）。

    Example:
        >>> git_commit(repo="/project", message="feat: add login")
        'a1b2c3d4'
    """
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    _git(*args, repo=repo)
    # 取最新 commit hash
    return _git("rev-parse", "--short=8", "HEAD", repo=repo).strip()


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------

@dataclass
class Commit:
    hash: str
    author: str
    date: str
    message: str


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


# ---------------------------------------------------------------------------
# git_branch
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# git_checkout
# ---------------------------------------------------------------------------

def git_checkout(ref: str, *, repo: str | Path) -> None:
    """単次切换分支或还原文件到某 ref。

    Args:
        ref: 分支名、tag 或 commit hash。若需还原文件，使用 paths 参数。
        repo: Git 仓库根目录。

    Raises:
        GitOprimError: checkout 失败。

    Example:
        >>> git_checkout("main", repo="/project")
    """
    # 支持 "HEAD -- file.py" 形式，拆分为多参数
    parts = ref.split()
    _git("checkout", *parts, repo=repo)


# ---------------------------------------------------------------------------
# git_stash
# ---------------------------------------------------------------------------

def git_stash(*, repo: str | Path, pop: bool = False, message: str = "") -> str:
    """单次 stash 操作（push 或 pop）。

    Args:
        repo: Git 仓库根目录。
        pop: True 时执行 stash pop，False 时执行 stash push。
        message: stash push 时的描述（可选）。

    Returns:
        git stash 输出字符串。

    Raises:
        GitOprimError: stash 操作失败。

    Example:
        >>> git_stash(repo="/project")              # push
        >>> git_stash(repo="/project", pop=True)   # pop
    """
    if pop:
        return _git("stash", "pop", repo=repo).strip()
    args = ["stash", "push"]
    if message:
        args.extend(["-m", message])
    return _git(*args, repo=repo).strip()


# ---------------------------------------------------------------------------
# git_show
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# git_blame
# ---------------------------------------------------------------------------

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
