"""Filesystem oprim — 3 atomic filesystem operations."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from oprim._exceptions import (
    OprimError,
    OprimNotFoundError,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DiskUsage(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float


class ArchiveResult(BaseModel):
    sources: list[str]
    dst_path: str
    archive_bytes: int
    file_count: int
    elapsed_ms: int
    checksum_sha256: str

    @property
    def src_dir(self) -> str:
        import warnings

        msg = "ArchiveResult.src_dir is deprecated, use .sources"
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return self.sources[0] if self.sources else ""


# ---------------------------------------------------------------------------
# 7.1 disk_usage
# ---------------------------------------------------------------------------


def disk_usage(
    *,
    path: str,
) -> DiskUsage:
    """查 path 所在文件系统的使用情况.

    Args:
        path: 文件系统路径

    Returns:
        DiskUsage 含 total / used / free bytes 和使用率

    Raises:
        OprimNotFoundError: path 不存在
    """
    p = Path(path)
    if not p.exists():
        raise OprimNotFoundError(f"Path not found: {path}")

    usage = shutil.disk_usage(path)
    used_percent = (usage.used / usage.total * 100.0) if usage.total > 0 else 0.0

    return DiskUsage(
        path=str(p.resolve()),
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        used_percent=round(used_percent, 2),
    )


# ---------------------------------------------------------------------------
# 7.2 archive_to_targz
# ---------------------------------------------------------------------------


def _matches_any(name: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def archive_to_targz(
    *,
    sources: list[str],
    dst_path: str,
    exclude_patterns: list[str] | None = None,
    follow_symlinks: bool = False,
) -> ArchiveResult:
    """把多个目录或文件打包为 tar.gz.

    Args:
        sources: 源路径列表
        dst_path: 目标 tar.gz 路径
        exclude_patterns: glob 排除模式列表
        follow_symlinks: 是否跟随符号链接

    Returns:
        ArchiveResult 含文件数 / 大小 / checksum

    Raises:
        OprimNotFoundError: 某个源不存在
        OprimError: 写入失败
    """
    if not sources:
        raise OprimError("No sources provided for archiving")

    excludes = exclude_patterns or []
    t0 = time.monotonic()
    file_count = 0

    try:
        with tarfile.open(dst_path, "w:gz") as tar:
            for s_path in sources:
                src = Path(s_path)
                if not src.exists():
                    raise OprimNotFoundError(f"Source not found: {s_path}")

                if src.is_dir():
                    # Walk directory
                    for file_path in sorted(src.rglob("*")):
                        # Use relative path from src's parent to keep the src dir name in archive
                        # or relative to src to put contents in root.
                        # dir_archive_to_targz used relative_to(src), so let's stick to that for dir contents.
                        rel = file_path.relative_to(src)
                        if any(_matches_any(part, excludes) for part in rel.parts):
                            continue
                        if not follow_symlinks and file_path.is_symlink():
                            continue

                        # If we want multiple sources to coexist, we should probably keep their names
                        # But dir_archive_to_targz logic was rel = file_path.relative_to(src)
                        # and arcname = str(rel). This means if sources=[dir1, dir2], their contents
                        # will be mixed in the root of the archive.
                        arcname = str(rel)
                        if not arcname or arcname == ".":
                            continue
                        tar.add(str(file_path), arcname=arcname, recursive=False)
                        if file_path.is_file():
                            file_count += 1
                else:
                    if any(_matches_any(part, excludes) for part in src.parts):
                        continue
                    tar.add(str(src), arcname=src.name, recursive=False)
                    file_count += 1
    except (OSError, tarfile.TarError) as exc:
        if isinstance(exc, (OprimNotFoundError, OprimError)):
            raise
        raise OprimError(f"Failed to create archive at {dst_path}: {exc}") from exc

    elapsed = int((time.monotonic() - t0) * 1000)

    # Compute SHA-256 of the archive
    h = hashlib.sha256()
    try:
        with open(dst_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError as exc:
        raise OprimError(f"Failed to read archive for checksum: {exc}") from exc

    archive_bytes = Path(dst_path).stat().st_size

    return ArchiveResult(
        sources=sources,
        dst_path=dst_path,
        archive_bytes=archive_bytes,
        file_count=file_count,
        elapsed_ms=elapsed,
        checksum_sha256=h.hexdigest(),
    )


def dir_archive_to_targz(
    *,
    src_dir: str,
    dst_path: str,
    exclude_patterns: list[str] | None = None,
    follow_symlinks: bool = False,
) -> ArchiveResult:
    """(Deprecated) use archive_to_targz."""
    import warnings

    msg = "dir_archive_to_targz is deprecated, use archive_to_targz"
    warnings.warn(msg, DeprecationWarning, stacklevel=2)
    return archive_to_targz(
        sources=[src_dir],
        dst_path=dst_path,
        exclude_patterns=exclude_patterns,
        follow_symlinks=follow_symlinks,
    )


# ---------------------------------------------------------------------------
# 7.3 file_checksum
# ---------------------------------------------------------------------------


def file_checksum(
    *,
    file_path: str,
    algorithm: Literal["sha256", "md5", "sha1"] = "sha256",
    chunk_size: int = 65536,
) -> str:
    """计算文件 checksum.

    Args:
        file_path: 文件路径
        algorithm: 哈希算法 ("sha256", "md5", "sha1")
        chunk_size: 流式读取块大小 (bytes)

    Returns:
        十六进制 checksum 字符串

    Raises:
        OprimNotFoundError: 文件不存在
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise OprimNotFoundError(f"File not found: {file_path}")

    h = hashlib.new(algorithm)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — short-name alias + fs_inode_check (B2)
# ---------------------------------------------------------------------------

fs_disk_usage = disk_usage


def fs_inode_check(
    *,
    path: str,
) -> dict[str, int | float | str]:
    """检查文件系统 inode 使用情况.

    Args:
        path: 目标路径 (任意挂载点内的路径即可)

    Returns:
        {
          "path": str,
          "inodes_total": int,
          "inodes_used": int,
          "inodes_free": int,
          "inodes_used_percent": float,
        }

    Raises:
        OprimNotFoundError: path 不存在
        OprimError: 平台不支持 inode 统计
    """
    p = Path(path)
    if not p.exists():
        raise OprimNotFoundError(f"Path not found: {path}")

    try:
        st = shutil.disk_usage(str(p))  # total/used/free bytes
    except Exception as exc:
        raise OprimError(f"Failed to stat path: {exc}") from exc

    try:
        import os

        stat_vfs = os.statvfs(str(p))
        total = stat_vfs.f_files
        free = stat_vfs.f_ffree
        used = total - free
        pct = round(used / total * 100, 2) if total > 0 else 0.0
    except AttributeError:
        raise OprimError("fs_inode_check is not supported on this platform (no os.statvfs)")

    return {
        "path": str(p),
        "inodes_total": total,
        "inodes_used": used,
        "inodes_free": free,
        "inodes_used_percent": pct,
    }
