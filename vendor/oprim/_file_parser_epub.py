"""Parse an EPUB file and extract text, chapters, and metadata."""

from __future__ import annotations

from pathlib import Path

import ebooklib  # type: ignore[import-untyped]
from bs4 import BeautifulSoup
from ebooklib import epub

from oprim._document_types import Page, ParsedDocument
from oprim._exceptions import OprimError


def file_parser_epub(*, file_path: Path) -> ParsedDocument:
    """Parse an EPUB file and extract text, chapters, and metadata.

    Args:
        file_path: Path to the EPUB file

    Returns:
        ParsedDocument with pages (one per chapter), metadata

    Raises:
        OprimError: File not found, DRM protected, or parse failed
    """
    if not file_path.exists():
        raise OprimError(f"file_not_found: {file_path}")

    try:
        book = epub.read_epub(str(file_path))
    except Exception as e:
        err_str = str(e).lower()
        if "drm" in err_str or "decrypt" in err_str or "encrypted" in err_str:
            raise OprimError("drm_protected: EPUB is DRM-protected") from e
        raise OprimError(f"epub_parse_failed: {e}") from e

    # Build TOC title map
    toc_map: dict[str, str] = {}
    def _walk(nodes):
        for node in nodes:
            if hasattr(node, "href") and hasattr(node, "title"):
                toc_map[node.href.split("#")[0]] = node.title
            if hasattr(node, "__iter__") and not hasattr(node, "href"):
                _walk(node)
    _walk(book.toc)

    pages = []
    for i, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), 1):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n").strip()
        if text:
            title = toc_map.get(item.get_name(), item.get_name())
            pages.append(Page(page_number=i, text=text, title=title))

    raw_metadata = {
        "title": book.get_metadata("DC", "title"),
        "creator": book.get_metadata("DC", "creator"),
        "language": book.get_metadata("DC", "language"),
    }

    metadata: dict[str, str] = {}
    for k, v in raw_metadata.items():
        if v:
            metadata[k] = str(v[0][0])

    return ParsedDocument(
        source_path=str(file_path),
        pages=pages,
        metadata=metadata,
        status="ok",
    )
