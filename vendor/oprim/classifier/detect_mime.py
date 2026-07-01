"""Detect MIME type of a file using libmagic."""
from __future__ import annotations

from pathlib import Path

import magic

from oprim._logging import log as olog


def detect_mime(path: Path) -> str:
    """Return the MIME type string for *path*.

    Raises:
        FileNotFoundError: if the file does not exist or is not a regular file.
        PermissionError: if the file cannot be read.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    # Test read permission early for a clear error
    try:
        path.open("rb").read(1)
    except PermissionError:
        raise
    try:
        mime = magic.from_file(str(path), mime=True)
        olog.emit("detect_mime", path=str(path), mime=mime)
        return mime
    except Exception as e:
        olog.error("detect_mime failed", path=str(path), error=str(e))
        raise
