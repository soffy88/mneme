"""Extract a short text sample from a file for classification purposes."""
from __future__ import annotations

import re
from pathlib import Path

import chardet
import fitz
import trafilatura

from oprim._logging import log as olog
from oprim.errors import UnsupportedFileTypeError

_SUPPORTED_MIMES = frozenset({
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/html",
    "application/epub+zip",
    "text/x-markdown",
})


def extract_text_sample(path: Path, mime: str, max_chars: int = 2000) -> str:
    """Extract up to *max_chars* characters of plain text from *path*.

    Raises:
        FileNotFoundError: file does not exist.
        UnsupportedFileTypeError: *mime* is not supported.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if mime == "application/pdf":
        return _from_pdf(path, max_chars)
    elif mime in ("text/plain", "text/markdown", "text/x-markdown"):
        return _from_text(path, max_chars)
    elif mime == "text/html":
        return _from_html(path, max_chars)
    elif mime == "application/epub+zip":
        return _from_epub(path, max_chars)
    else:
        raise UnsupportedFileTypeError(f"No text extraction for MIME: {mime}")


def _from_pdf(path: Path, max_chars: int) -> str:
    try:
        doc = fitz.open(str(path))
        text = ""
        for i in range(min(3, len(doc))):
            text += doc[i].get_text()
            if len(text) >= max_chars:
                break
        doc.close()
        return text[:max_chars]
    except Exception as e:
        olog.error("extract_text_sample pdf failed", path=str(path), error=str(e))
        return ""


def _from_text(path: Path, max_chars: int) -> str:
    raw = path.read_bytes()
    if not raw:
        return ""
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    try:
        return raw.decode(enc, errors="replace")[:max_chars]
    except Exception:
        return raw.decode("utf-8", errors="replace")[:max_chars]


def _from_html(path: Path, max_chars: int) -> str:
    raw = path.read_bytes()
    if not raw:
        return ""
    enc = chardet.detect(raw).get("encoding") or "utf-8"
    html_str = raw.decode(enc, errors="replace")
    text = trafilatura.extract(html_str) or ""
    return text[:max_chars]


def _from_epub(path: Path, max_chars: int) -> str:
    try:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path))
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content().decode("utf-8", errors="replace")
            plain = re.sub(r"<[^>]+>", " ", content)
            text += plain + "\n"
            if len(text) >= max_chars:
                break
        return text[:max_chars]
    except Exception as e:
        olog.error("extract_text_sample epub failed", path=str(path), error=str(e))
        return ""
