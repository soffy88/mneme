"""Detect the MIME type and category of a file using magic bytes."""

from __future__ import annotations

from pathlib import Path

import magic
from pydantic import BaseModel

from oprim._exceptions import OprimError

_SUPPORTED_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/epub+zip",
        "text/html",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }
)

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".cs",
        ".sh",
        ".bash",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".xml",
        ".sql",
    }
)

_ARCHIVE_MIMES: frozenset[str] = frozenset(
    {
        "application/zip",
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-bzip2",
        "application/x-xz",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/vnd.rar",
    }
)


class FileTypeInfo(BaseModel):
    mime_type: str
    extension: str
    category: str  # "document" | "image" | "audio" | "video" | "archive" | "code" | "other"
    is_supported: bool


def _categorize(mime_type: str, extension: str) -> str:
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type in _ARCHIVE_MIMES:
        return "archive"
    if mime_type == "application/pdf":
        return "document"
    if mime_type.startswith("text/"):
        if extension in _CODE_EXTENSIONS:
            return "code"
        return "document"
    if ("xml" in mime_type or "json" in mime_type) and extension in _CODE_EXTENSIONS:
        return "code"
    return "other"


def _is_supported(mime_type: str, category: str) -> bool:
    if category in {"image", "audio", "video"}:
        return True
    if mime_type in _SUPPORTED_MIMES:
        return True
    return bool(mime_type.startswith("text/"))


def file_type_detector(*, file_path: Path) -> FileTypeInfo:
    """Detect the MIME type and category of a file using magic bytes.

    Args:
        file_path: Path to the file

    Returns:
        FileTypeInfo with MIME type, extension, category

    Raises:
        OprimError: File does not exist or cannot be read

    Example:
        >>> info = file_type_detector(file_path=Path("doc.pdf"))
        >>> info.mime_type
        'application/pdf'
    """
    if not file_path.exists():
        raise OprimError("file_not_found")

    try:
        mime_type = magic.from_file(str(file_path), mime=True)
    except Exception as e:
        raise OprimError(f"cannot_read_file: {e}") from e

    extension = file_path.suffix.lower()
    category = _categorize(mime_type, extension)
    supported = _is_supported(mime_type, category)

    return FileTypeInfo(
        mime_type=mime_type,
        extension=extension,
        category=category,
        is_supported=supported,
    )
