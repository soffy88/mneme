"""H-B A组: 文件 IO 扩展 (5)
ensure_parent_dir / file_read_bytes / image_to_base64 / atomic_write / backup_before_overwrite
"""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
import warnings
from pathlib import Path


async def ensure_parent_dir(path: Path) -> None:
    """创建 path 的父目录链（幂等，递归）。

    Args:
        path: 目标路径；其父目录将被创建。

    Raises:
        NotADirectoryError: 父路径上存在同名普通文件。
        PermissionError: 无权限创建目录。

    Example:
        >>> await ensure_parent_dir(Path("/tmp/a/b/c/file.txt"))
        # /tmp/a/b/c/ 已存在（幂等）
    """
    parent = Path(path).parent
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: parent.mkdir(parents=True, exist_ok=True))


async def file_read_bytes(
    path: Path,
    *,
    offset: int = 0,
    length: int | None = None,
) -> bytes:
    """读字节范围（图片/二进制 part 用）。

    Args:
        path: 文件路径。
        offset: 起始字节偏移（0-based）；超出文件大小返回 b""。
        length: 读取字节数；None 表示读到末尾。

    Returns:
        指定范围的字节数据。

    Raises:
        ValueError: offset < 0。
        FileNotFoundError: 文件不存在。
        PermissionError: 无权限。

    Example:
        >>> data = await file_read_bytes(Path("/tmp/img.png"), offset=0, length=4)
        >>> data[:4]
        b'\\x89PNG'
    """
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")

    p = Path(path)

    def _read() -> bytes:
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if offset >= size and size > 0:
                return b""
            if offset > 0:
                f.seek(offset)
            else:
                f.seek(0)
            return f.read() if length is None else f.read(length)

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _read)
    except FileNotFoundError:
        raise FileNotFoundError(f"file not found: {path}")
    except PermissionError as e:
        raise PermissionError(f"permission denied: {path}") from e


async def image_to_base64(path: Path) -> str:
    """图片 → base64 编码字符串（多模态 part 用）。

    内容不校验（mime 由 detect_mime 另判）。超过 20 MB 时发出警告。

    Args:
        path: 图片路径。

    Returns:
        base64 编码的 ASCII 字符串。

    Raises:
        FileNotFoundError: 文件不存在。

    Example:
        >>> b64 = await image_to_base64(Path("/tmp/photo.png"))
        >>> import base64, pathlib
        >>> data = base64.b64decode(b64)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"image not found: {path}")
    size = p.stat().st_size
    if size > 20 * 1024 * 1024:
        warnings.warn(
            f"image_to_base64: large file {size:,} bytes: {path}",
            ResourceWarning,
            stacklevel=2,
        )

    def _encode() -> str:
        return base64.b64encode(p.read_bytes()).decode("ascii")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _encode)


async def atomic_write(path: Path, *, content: str, encoding: str = "utf-8") -> None:
    """原子写（临时文件 + rename）防写一半崩溃。

    父目录不存在时自动创建。

    Args:
        path: 目标文件路径。
        content: 写入内容。
        encoding: 编码，默认 utf-8。

    Raises:
        PermissionError: 无写权限。
        OSError: 磁盘满等底层 IO 错误。

    Example:
        >>> await atomic_write(Path("/tmp/out.txt"), content="hello")
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        dir_ = p.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".atomic_")
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(tmp_path, p)
            except OSError:
                # cross-filesystem fallback: copy then remove temp
                shutil.copy2(tmp_path, str(p))
                os.unlink(tmp_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def backup_before_overwrite(path: Path) -> Path | None:
    """覆盖前备份（undo 辅助），返回备份路径；不存在返回 None。

    备份文件名: `path.bak`；冲突时依次尝试 `.bak1`, `.bak2`, …。

    Args:
        path: 待备份文件路径。

    Returns:
        备份文件 Path；原文件不存在返回 None。

    Raises:
        PermissionError: 无权限创建备份。

    Example:
        >>> bak = await backup_before_overwrite(Path("/tmp/config.yaml"))
        >>> # bak == Path("/tmp/config.yaml.bak")
    """
    p = Path(path)
    if not p.exists():
        return None

    bak = p.with_name(p.name + ".bak")
    counter = 0
    while bak.exists():
        counter += 1
        bak = p.with_name(f"{p.name}.bak{counter}")

    def _copy() -> None:
        shutil.copy2(str(p), str(bak))

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _copy)
    return bak
