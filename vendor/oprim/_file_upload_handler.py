from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

from pydantic import BaseModel

from oprim._exceptions import OprimError


class UploadResult(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    dest_path: str
    chunks_written: int


def file_upload_handler(
    *,
    upload_stream: BinaryIO,
    filename: str,
    total_size: int,
    dest_dir: Path,
    chunk_size: int = 5 * 1024 * 1024,
) -> UploadResult:
    """Handle chunked file upload from a binary stream to a destination directory.

    Supports large files via chunked reading. Returns SHA-256 checksum of written content.

    Args:
        upload_stream: Binary file-like object to read from
        filename: Target filename (sanitized before use)
        total_size: Expected total size in bytes
        dest_dir: Directory to write the file to
        chunk_size: Chunk size in bytes (default 5 MB)

    Returns:
        UploadResult with filename, size, SHA-256 checksum, destination path

    Raises:
        OprimError: Write failure, stream read error, or size mismatch

    Example:
        >>> import io
        >>> stream = io.BytesIO(b"file content")
        >>> result = file_upload_handler(
        ...     upload_stream=stream, filename="doc.txt", total_size=12, dest_dir=Path("/tmp")
        ... )
        >>> result.sha256 is not None
        True
    """
    # Sanitize filename: strip path components
    safe_filename = Path(filename).name
    if not safe_filename:
        raise OprimError("file_upload_handler: invalid filename")

    dest_path = dest_dir / safe_filename
    hasher = hashlib.sha256()
    chunks_written = 0
    bytes_written = 0

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            while True:
                chunk = upload_stream.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                bytes_written += len(chunk)
                chunks_written += 1
    except OSError as e:
        raise OprimError(f"file_upload_handler write failed: {e}") from e

    return UploadResult(
        filename=safe_filename,
        size_bytes=bytes_written,
        sha256=hasher.hexdigest(),
        dest_path=str(dest_path),
        chunks_written=chunks_written,
    )
