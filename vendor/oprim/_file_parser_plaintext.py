"""Parse a plain text file with encoding detection."""

from __future__ import annotations

from pathlib import Path

import chardet

from oprim._document_types import ParsedPlaintext
from oprim._exceptions import OprimError


def file_parser_plaintext(*, file_path: Path) -> ParsedPlaintext:
    """Parse a plain text file with encoding detection.

    Args:
        file_path: Path to the text file

    Returns:
        ParsedPlaintext with encoding, paragraphs, line_count

    Raises:
        OprimError: File not found or read error
    """
    if not file_path.exists():
        raise OprimError(f"file_not_found: {file_path}")

    raw = file_path.read_bytes()
    detected = chardet.detect(raw)
    encoding = detected.get("encoding") or "utf-8"

    try:
        text = raw.decode(encoding, errors="replace")
    except Exception as e:
        raise OprimError(f"plaintext_decode_failed: {e}") from e

    lines = text.splitlines()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    return ParsedPlaintext(
        source_path=str(file_path),
        encoding=encoding,
        paragraphs=paragraphs,
        line_count=len(lines),
        language_hint=None,
    )
