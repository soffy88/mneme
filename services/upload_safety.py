"""Common upload boundary checks for every user-supplied file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".epub": {"application/epub+zip", "application/octet-stream"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
}


class UploadValidationError(ValueError):
    """Safe, user-facing upload validation failure."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def max_upload_bytes() -> int:
    raw = os.environ.get("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise UploadValidationError("上传大小配置无效") from exc
    if value <= 0:
        raise UploadValidationError("上传大小配置无效")
    return value


def validate_filename(filename: str | None, *, allowed_extensions: set[str] | None = None) -> str:
    name = filename or "untitled"
    if "\x00" in name or "\\" in name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise UploadValidationError("文件名不安全")
    safe = Path(name).name
    if safe in {"", ".", ".."}:
        raise UploadValidationError("文件名不安全")
    extension = Path(safe).suffix.lower()
    if allowed_extensions is not None and extension not in allowed_extensions:
        raise UploadValidationError("不支持的文件类型")
    return safe


def validate_content_type(filename: str, content_type: str | None) -> None:
    expected = _CONTENT_TYPES.get(Path(filename).suffix.lower())
    if expected and content_type and content_type.lower() not in expected:
        raise UploadValidationError("文件类型与内容不匹配")


def validate_size(size: int, *, limit: int | None = None) -> None:
    if size < 0 or size > (max_upload_bytes() if limit is None else limit):
        raise UploadValidationError("文件过大", status_code=413)


def safe_upload_path(root: Path, filename: str) -> Path:
    safe = validate_filename(filename)
    root_resolved = root.resolve()
    candidate = (root_resolved / safe).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise UploadValidationError("文件路径不安全")
    return candidate


def copy_stream(stream: BinaryIO, destination: Path, *, limit: int | None = None) -> int:
    """Copy with a hard cap; callers can remove the partial file on failure."""

    maximum = max_upload_bytes() if limit is None else limit
    written = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = stream.read(min(1024 * 1024, maximum - written + 1))
                if not chunk:
                    break
                written += len(chunk)
                if written > maximum:
                    raise UploadValidationError("文件过大", status_code=413)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return written


def cleanup_failed_upload(path: Path) -> None:
    """Best-effort cleanup for a failed upload; never raises into the worker."""

    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = ["DEFAULT_MAX_UPLOAD_BYTES", "UploadValidationError", "cleanup_failed_upload", "copy_stream", "max_upload_bytes", "safe_upload_path", "validate_content_type", "validate_filename", "validate_size"]
