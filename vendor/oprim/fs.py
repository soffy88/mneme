"""
oprim: 文件系统原子操作集
==========================
包含：file_read / file_write / file_append / file_stat / file_delete
      dir_list / glob_match / path_resolve / read_gitignore

归属约束 (§3 SPEC v2.1)
------------------------
✅ 每个函数 = 单次原子 IO 操作
✅ ≤1 个核心位置参数，其余 keyword-only
✅ 失败抛 FileOprimError / PathSecurityError（不吞异常）
✅ oprim 之间不裸调（互不依赖）
✅ 不写 decision_trail / 不做业务编排
"""

from __future__ import annotations

import stat
from pathlib import Path

from ._exceptions import FileOprimError, PathSecurityError

# ---------------------------------------------------------------------------
# path_resolve — 路径解析 + 沙箱安全校验
# ---------------------------------------------------------------------------

def path_resolve(
    path: str | Path,
    *,
    sandbox_root: str | Path | None = None,
) -> Path:
    """解析路径为绝对路径，可选沙箱越界校验。

    Args:
        path: 待解析的路径（相对或绝对）。
        sandbox_root: 若提供，校验 resolved 路径在此目录内；越界抛
            PathSecurityError。

    Returns:
        解析后的 Path 对象（绝对路径）。

    Raises:
        PathSecurityError: 路径超出 sandbox_root 范围。

    Example:
        >>> path_resolve("src/main.py", sandbox_root="/project")
        PosixPath('/project/src/main.py')  # 视 cwd 而定
    """
    resolved = Path(path).resolve()
    if sandbox_root is not None:
        root = Path(sandbox_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PathSecurityError(
                f"path '{resolved}' is outside sandbox root '{root}'"
            )
    return resolved


# ---------------------------------------------------------------------------
# file_read
# ---------------------------------------------------------------------------

def file_read(
    path: str | Path,
    *,
    start: int | None = None,
    end: int | None = None,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str:
    """单次原子读取文件内容，支持行范围切片。

    Args:
        path: 文件路径。
        start: 起始行号（0-based，含）；None 表示从头。
        end: 结束行号（0-based，不含）；None 表示到末尾。
        encoding: 文件编码，默认 utf-8。
        errors: 编码错误处理策略，默认 replace。

    Returns:
        文件内容字符串（已按行切片，若提供了 start/end）。

    Raises:
        FileOprimError: 文件不存在或读取失败。

    Example:
        >>> file_read("README.md")
        >>> file_read("src/main.py", start=0, end=20)
    """
    p = Path(path)
    try:
        text = p.read_text(encoding=encoding, errors=errors)
    except FileNotFoundError:
        raise FileOprimError(f"file not found: {path}")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read '{path}'", cause=e)

    if start is None and end is None:
        return text

    lines = text.splitlines(keepends=True)
    return "".join(lines[start:end])


# ---------------------------------------------------------------------------
# file_write
# ---------------------------------------------------------------------------

def file_write(
    path: str | Path,
    *,
    content: str,
    encoding: str = "utf-8",
    mkdirs: bool = True,
) -> Path:
    """单次原子写入文件（覆盖）。

    Args:
        path: 目标文件路径。
        content: 写入内容。
        encoding: 编码，默认 utf-8。
        mkdirs: 若父目录不存在是否自动创建，默认 True。

    Returns:
        写入完成的 Path 对象。

    Raises:
        FileOprimError: 写入失败。

    Example:
        >>> file_write("/tmp/out.py", content="x = 1\n")
    """
    p = Path(path)
    try:
        if mkdirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot write '{path}'", cause=e)
    return p


# ---------------------------------------------------------------------------
# file_append
# ---------------------------------------------------------------------------

def file_append(
    path: str | Path,
    *,
    content: str,
    encoding: str = "utf-8",
    mkdirs: bool = True,
) -> Path:
    """单次原子追加写入文件。

    Args:
        path: 目标文件路径。
        content: 追加内容。
        encoding: 编码，默认 utf-8。
        mkdirs: 若父目录不存在是否自动创建，默认 True。

    Returns:
        追加完成的 Path 对象。

    Raises:
        FileOprimError: 写入失败。

    Example:
        >>> file_append("/tmp/log.txt", content="new line\n")
    """
    p = Path(path)
    try:
        if mkdirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding=encoding) as f:
            f.write(content)
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot append to '{path}'", cause=e)
    return p


# ---------------------------------------------------------------------------
# file_stat
# ---------------------------------------------------------------------------

def file_stat(path: str | Path) -> dict[str, object]:
    """单次原子获取文件元数据。

    Args:
        path: 文件或目录路径。

    Returns:
        dict 含：
          - exists (bool)
          - is_file (bool)
          - is_dir (bool)
          - size (int): 字节数；若不存在为 0。
          - mtime (float): 修改时间戳；若不存在为 0.0。
          - mode (str): 八进制权限字符串，如 "0o644"。

    Raises:
        FileOprimError: stat 调用失败（权限等，非"不存在"）。

    Example:
        >>> file_stat("README.md")
        {'exists': True, 'is_file': True, 'size': 1024, ...}
    """
    p = Path(path)
    if not p.exists():
        return {
            "exists": False,
            "is_file": False,
            "is_dir": False,
            "size": 0,
            "mtime": 0.0,
            "mode": "0o000",
        }
    try:
        s = p.stat()
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot stat '{path}'", cause=e)
    return {
        "exists": True,
        "is_file": p.is_file(),
        "is_dir": p.is_dir(),
        "size": s.st_size,
        "mtime": s.st_mtime,
        "mode": oct(stat.S_IMODE(s.st_mode)),
    }


# ---------------------------------------------------------------------------
# file_delete
# ---------------------------------------------------------------------------

def file_delete(path: str | Path, *, missing_ok: bool = False) -> bool:
    """单次原子删除文件（不删目录）。

    Args:
        path: 文件路径。
        missing_ok: True 时文件不存在不抛异常，返回 False。

    Returns:
        True 表示成功删除；False 表示文件不存在（仅 missing_ok=True 时）。

    Raises:
        FileOprimError: 文件不存在（missing_ok=False）或删除失败。

    Example:
        >>> file_delete("/tmp/old.py")
        True
        >>> file_delete("/tmp/nonexist.py", missing_ok=True)
        False
    """
    p = Path(path)
    existed = p.exists()
    try:
        p.unlink(missing_ok=missing_ok)
    except FileNotFoundError:
        raise FileOprimError(f"file not found: {path}")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot delete '{path}'", cause=e)
    return existed  # True if the file existed and was deleted


# ---------------------------------------------------------------------------
# dir_list
# ---------------------------------------------------------------------------

def dir_list(
    path: str | Path,
    *,
    recursive: bool = False,
    include_hidden: bool = False,
) -> list[Path]:
    """单次原子列出目录内容。

    Args:
        path: 目录路径。
        recursive: 是否递归列出所有子目录内容。
        include_hidden: 是否包含以 . 开头的隐藏文件/目录。

    Returns:
        排序后的 Path 列表（相对于 path 的路径）。

    Raises:
        FileOprimError: 路径不存在或不是目录。

    Example:
        >>> dir_list("/project/src", recursive=True)
        [PosixPath('main.py'), PosixPath('utils/helper.py'), ...]
    """
    p = Path(path)
    if not p.exists():
        raise FileOprimError(f"directory not found: {path}")
    if not p.is_dir():
        raise FileOprimError(f"not a directory: {path}")

    try:
        if recursive:
            entries = [
                child.relative_to(p)
                for child in p.rglob("*")
                if include_hidden or not any(
                    part.startswith(".") for part in child.relative_to(p).parts
                )
            ]
        else:
            entries = [
                child.relative_to(p)
                for child in p.iterdir()
                if include_hidden or not child.name.startswith(".")
            ]
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot list '{path}'", cause=e)

    return sorted(entries)


# ---------------------------------------------------------------------------
# glob_match
# ---------------------------------------------------------------------------

def glob_match(
    pattern: str,
    *,
    root: str | Path,
    respect_gitignore: bool = True,
) -> list[Path]:
    """单次原子 glob 匹配，返回匹配文件列表。

    Args:
        pattern: glob 模式，如 "**/*.py" 或 "src/*.ts"。
        root: 搜索根目录。
        respect_gitignore: 若 True，过滤掉 .gitignore 中匹配的路径（简化实现：
            过滤 .git/ 目录及以 . 开头的目录）。

    Returns:
        排序后的绝对 Path 列表。

    Raises:
        FileOprimError: root 不存在或不是目录。

    Example:
        >>> glob_match("**/*.py", root="/project", respect_gitignore=True)
        [PosixPath('/project/src/main.py'), ...]
    """
    r = Path(root)
    if not r.exists():
        raise FileOprimError(f"root not found: {root}")
    if not r.is_dir():
        raise FileOprimError(f"root is not a directory: {root}")

    try:
        matches = list(r.glob(pattern))
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"glob failed for '{pattern}' in '{root}'", cause=e)

    if respect_gitignore:
        matches = [
            p for p in matches
            if ".git" not in p.parts
            and not any(part.startswith(".") for part in p.relative_to(r).parts)
        ]

    return sorted(matches)


# ---------------------------------------------------------------------------
# read_gitignore
# ---------------------------------------------------------------------------

def read_gitignore(root: str | Path) -> list[str]:
    """单次读取并解析 .gitignore 文件，返回规则列表。

    不存在时返回空列表（不抛异常）。注释行和空行被过滤。

    Args:
        root: 包含 .gitignore 的目录路径。

    Returns:
        gitignore 规则字符串列表（保留原始格式，不解析 negation）。

    Raises:
        FileOprimError: .gitignore 存在但读取失败。

    Example:
        >>> read_gitignore("/project")
        ['*.pyc', '__pycache__/', '.env', ...]
    """
    gitignore = Path(root) / ".gitignore"
    if not gitignore.exists():
        return []
    try:
        text = gitignore.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read .gitignore in '{root}'", cause=e)

    rules = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rules.append(stripped)
    return rules
