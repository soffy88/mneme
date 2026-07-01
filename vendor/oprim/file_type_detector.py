"""Detect file MIME type and category from file path."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileTypeInfo:
    mime_type: str
    category: str


_EXT_MAP: dict[str, tuple[str, str]] = {
    ".pdf":  ("application/pdf", "pdf"),
    ".epub": ("application/epub+zip", "epub"),
    ".mobi": ("application/x-mobipocket-ebook", "book"),
    ".md":   ("text/markdown", "text"),
    ".txt":  ("text/plain", "text"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
    ".html": ("text/html", "webpage"),
    ".htm":  ("text/html", "webpage"),
}


def file_type_detector(*, file_path: str | Path) -> FileTypeInfo:
    """Detect file type from extension.

    Args:
        file_path: Path to the file.

    Returns:
        FileTypeInfo with mime_type and category.

    Example:
        >>> file_type_detector(file_path="/tmp/paper.pdf")
        FileTypeInfo(mime_type='application/pdf', category='pdf')
    """
    suffix = Path(file_path).suffix.lower()
    mime_type, category = _EXT_MAP.get(suffix, ("application/octet-stream", "other"))
    return FileTypeInfo(mime_type=mime_type, category=category)
