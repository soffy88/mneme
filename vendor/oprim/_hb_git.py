"""H-B H组: Git 原子 + 纯计算 (7)
parse_git_status [s] / parse_git_diff [s] / parse_gitignore [s] /
detect_project_type / git_current_branch [BLOCK→就绪] /
git_snapshot [BLOCK→就绪] / git_restore_snapshot [BLOCK→就绪]

obase.git.run_git 已就位，[BLOCK] 全部实现。
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ._exceptions import GitOprimError


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class StatusEntry:
    path: str
    index: str      # staged status char: M/A/D/R/C/?/ (space)
    worktree: str   # worktree status char
    old_path: str | None = None


@dataclass
class GitStatus:
    files: list[StatusEntry] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.files

    @property
    def staged(self) -> list[StatusEntry]:
        return [f for f in self.files if f.index not in (" ", "?", "!")]

    @property
    def unstaged(self) -> list[StatusEntry]:
        return [f for f in self.files if f.worktree not in (" ", "?", "!")]

    @property
    def untracked(self) -> list[StatusEntry]:
        return [f for f in self.files if f.index == "?" and f.worktree == "?"]


@dataclass
class FileChange:
    new_path: str
    old_path: str | None = None
    status: str = ""   # A/M/D/R/C/B
    is_binary: bool = False
    additions: int = 0
    deletions: int = 0


@dataclass
class GitIgnorePattern:
    raw: str
    pattern: str
    negated: bool = False
    dir_only: bool = False
    anchored: bool = False


@dataclass
class ProjectType:
    languages: list[str] = field(default_factory=list)
    build_files: list[str] = field(default_factory=list)

    @property
    def primary(self) -> str:
        return self.languages[0] if self.languages else "unknown"

    @property
    def is_monorepo(self) -> bool:
        return len(self.languages) > 1


SnapshotId = str


# ---------------------------------------------------------------------------
# parse_git_status  [s] 纯计算
# ---------------------------------------------------------------------------

def parse_git_status(raw: str) -> GitStatus:
    """解析 `git status --porcelain=v1` 输出。

    Args:
        raw: git status --porcelain=v1 的 stdout 字符串。

    Returns:
        GitStatus（含 staged / unstaged / untracked 分组属性）。

    Example:
        >>> gs = parse_git_status("M  src/main.py\\n?? new_file.txt\\n")
        >>> gs.staged[0].path
        'src/main.py'
    """
    entries: list[StatusEntry] = []
    for line in raw.splitlines():
        if not line or len(line) < 4:
            continue
        index = line[0]
        worktree = line[1]
        rest = line[3:]
        old_path: str | None = None
        if " -> " in rest:
            old_path, rest = rest.split(" -> ", 1)
        entries.append(StatusEntry(
            path=rest.strip(),
            index=index,
            worktree=worktree,
            old_path=old_path,
        ))
    return GitStatus(files=entries)


# ---------------------------------------------------------------------------
# parse_git_diff  [s] 纯计算
# ---------------------------------------------------------------------------

_DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
_BINARY_MARK = re.compile(r"^Binary files")
_STAT_ADD = re.compile(r"^\+\+\+ b/(.+)$")
_HUNK_STAT = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def parse_git_diff(raw: str) -> list[FileChange]:
    """解析 git diff 输出 → 文件变更列表（纯计算）。

    Args:
        raw: git diff (unified format) 的 stdout 字符串。

    Returns:
        FileChange 列表。

    Example:
        >>> changes = parse_git_diff(diff_text)
        >>> changes[0].status
        'M'
    """
    if not raw.strip():
        return []

    changes: list[FileChange] = []
    current: FileChange | None = None

    for line in raw.splitlines():
        m = _DIFF_HEADER.match(line)
        if m:
            if current is not None:
                changes.append(current)
            old_p, new_p = m.group(1), m.group(2)
            current = FileChange(new_path=new_p, old_path=old_p if old_p != new_p else None)
            continue

        if current is None:
            continue

        if _BINARY_MARK.match(line):
            current.is_binary = True
            current.status = "B"
            continue

        if line.startswith("new file mode"):
            current.status = "A"
        elif line.startswith("deleted file mode"):
            current.status = "D"
        elif line.startswith("rename "):
            current.status = "R"
        elif line.startswith("+") and not line.startswith("+++"):
            current.additions += 1
            if not current.status:
                current.status = "M"
        elif line.startswith("-") and not line.startswith("---"):
            current.deletions += 1
            if not current.status:
                current.status = "M"

    if current is not None:
        changes.append(current)

    # Ensure status is set
    for c in changes:
        if not c.status:
            c.status = "M"

    return changes


# ---------------------------------------------------------------------------
# parse_gitignore  [s] 纯计算
# ---------------------------------------------------------------------------

def parse_gitignore(content: str) -> list[GitIgnorePattern]:
    """解析 .gitignore 内容 → pattern 列表（纯计算）。

    Args:
        content: .gitignore 文件内容字符串。

    Returns:
        GitIgnorePattern 列表（过滤空行和注释行）。

    Example:
        >>> patterns = parse_gitignore("*.pyc\\n!keep.pyc\\n# comment\\n__pycache__/\\n")
        >>> patterns[0].pattern
        '*.pyc'
        >>> patterns[1].negated
        True
    """
    patterns: list[GitIgnorePattern] = []
    for raw_line in content.splitlines():
        raw = raw_line
        stripped = raw_line.strip()

        # Empty or comment
        if not stripped or stripped.startswith("#"):
            continue

        negated = stripped.startswith("!")
        pattern = stripped[1:] if negated else stripped

        # Unescape leading space
        if pattern.startswith("\\ "):
            pattern = pattern[1:]

        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern.rstrip("/")

        # Anchored if contains slash in middle or starts with slash
        anchored = "/" in pattern.lstrip("/") or pattern.startswith("/")
        if pattern.startswith("/"):
            pattern = pattern[1:]

        patterns.append(GitIgnorePattern(
            raw=raw,
            pattern=pattern,
            negated=negated,
            dir_only=dir_only,
            anchored=anchored,
        ))
    return patterns


# ---------------------------------------------------------------------------
# detect_project_type  (async, reads disk, no git dependency)
# ---------------------------------------------------------------------------

_MARKERS: list[tuple[str, str]] = [
    ("go.mod", "go"),
    ("Cargo.toml", "rust"),
    ("package.json", "node"),
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("setup.cfg", "python"),
    ("requirements.txt", "python"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "kotlin"),
    ("Gemfile", "ruby"),
    ("mix.exs", "elixir"),
    ("composer.json", "php"),
    ("pubspec.yaml", "dart"),
    ("CMakeLists.txt", "cpp"),
    ("*.csproj", "csharp"),
    ("*.fsproj", "fsharp"),
    ("*.sln", "dotnet"),
    ("Makefile", "c"),
    ("deno.json", "deno"),
    ("deno.jsonc", "deno"),
]


async def detect_project_type(root: Path) -> ProjectType:
    """探测项目类型（读磁盘标志文件，不依赖 git）。

    Args:
        root: 项目根目录。

    Returns:
        ProjectType（languages 列表，多语言 is_monorepo=True）。

    Example:
        >>> pt = await detect_project_type(Path("/my/project"))
        >>> pt.primary
        'python'
    """
    root = Path(root)
    loop = asyncio.get_event_loop()

    def _detect() -> ProjectType:
        found_langs: list[str] = []
        found_files: list[str] = []
        seen: set[str] = set()

        for marker, lang in _MARKERS:
            if "*" in marker:
                matches = list(root.glob(marker))
                if matches and lang not in seen:
                    seen.add(lang)
                    found_langs.append(lang)
                    found_files.append(str(matches[0].relative_to(root)))
            else:
                if (root / marker).exists() and lang not in seen:
                    seen.add(lang)
                    found_langs.append(lang)
                    found_files.append(marker)

        return ProjectType(languages=found_langs or [], build_files=found_files)

    return await loop.run_in_executor(None, _detect)


# ---------------------------------------------------------------------------
# git_current_branch  [obase.git.run_git 就绪]
# ---------------------------------------------------------------------------

async def git_current_branch(*, cwd: Path, timeout: float = 15) -> str:
    """当前 git 分支名。detached HEAD 返回 commit hash 短串。

    Args:
        cwd: git 仓库目录（或子目录）。
        timeout: 超时秒数，默认 15。

    Returns:
        分支名字符串。

    Raises:
        GitOprimError: 非 git 仓库。
        TimeoutError: 超时。

    Example:
        >>> branch = await git_current_branch(cwd=Path("/project"))
        >>> branch
        'main'
    """
    from obase.git import run_git

    result = await run_git(["branch", "--show-current"], cwd=Path(cwd), timeout=timeout)
    if result.ok:
        branch = result.stdout.strip()
        if branch:
            return branch
        # Detached HEAD — return short hash
        rev = await run_git(["rev-parse", "--short", "HEAD"], cwd=Path(cwd), timeout=timeout)
        if rev.ok:
            return rev.stdout.strip()
        return ""
    # Check if truly not a git repo
    check = await run_git(["rev-parse", "--git-dir"], cwd=Path(cwd), timeout=timeout)
    if not check.ok:
        raise GitOprimError(f"not a git repository: {cwd}")
    return ""


# ---------------------------------------------------------------------------
# git_snapshot  [obase.git.run_git 就绪]
# ---------------------------------------------------------------------------

async def git_snapshot(*, cwd: Path, timeout: float = 30) -> SnapshotId:
    """创建工作区快照（stash push），返回可恢复 SnapshotId。

    无变更时仍返回一个带 'empty:' 前缀的 id（恢复时 no-op）。

    Args:
        cwd: git 仓库根目录。
        timeout: 超时秒数，默认 30。

    Returns:
        SnapshotId 字符串。

    Raises:
        GitOprimError: git 操作失败。
        TimeoutError: 超时。

    Example:
        >>> snap_id = await git_snapshot(cwd=Path("/project"))
    """
    from obase.git import run_git

    snap_id = f"oprim-snap-{uuid.uuid4().hex[:12]}"
    result = await run_git(
        ["stash", "push", "--include-untracked", "-m", snap_id],
        cwd=Path(cwd),
        timeout=timeout,
    )
    if not result.ok:
        if "No local changes" in result.stderr or "No local changes" in result.stdout:
            return f"empty:{snap_id}"
        raise GitOprimError(
            f"git_snapshot failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return snap_id


# ---------------------------------------------------------------------------
# git_restore_snapshot  [obase.git.run_git 就绪]
# ---------------------------------------------------------------------------

async def git_restore_snapshot(
    snap_id: SnapshotId,
    *,
    cwd: Path,
    timeout: float = 30,
) -> None:
    """恢复快照（stash pop）。

    Args:
        snap_id: git_snapshot 返回的 SnapshotId。
        cwd: git 仓库根目录。
        timeout: 超时秒数，默认 30。

    Raises:
        ValueError: snap_id 不存在于 stash。
        GitOprimError: git 操作失败（冲突等）。
        TimeoutError: 超时。

    Example:
        >>> await git_restore_snapshot(snap_id, cwd=Path("/project"))
    """
    if str(snap_id).startswith("empty:"):
        return  # empty snapshot — nothing to restore

    from obase.git import run_git

    list_result = await run_git(["stash", "list"], cwd=Path(cwd), timeout=timeout)
    if not list_result.ok:
        raise GitOprimError(f"cannot list stash: {list_result.stderr.strip()}")

    stash_ref: str | None = None
    for line in list_result.stdout.splitlines():
        if snap_id in line:
            stash_ref = line.split(":")[0].strip()
            break

    if stash_ref is None:
        raise ValueError(f"snapshot {snap_id!r} not found in stash")

    restore = await run_git(
        ["stash", "pop", stash_ref],
        cwd=Path(cwd),
        timeout=timeout,
    )
    if not restore.ok:
        raise GitOprimError(
            f"git_restore_snapshot failed (exit {restore.returncode}): "
            f"{restore.stderr.strip()}"
        )
