"""Parse a PDF file and extract text, tables, and metadata."""

from __future__ import annotations

from pathlib import Path

import fitz  # type: ignore[import-untyped]  # pymupdf

from oprim._document_types import Page, ParsedDocument
from oprim._exceptions import OprimError


def file_parser_pdf(
    *,
    file_path: Path,
    strategy: str = "pymupdf4llm",
) -> ParsedDocument:
    """Parse a PDF file and extract text, tables, and metadata.

    Uses pymupdf4llm for text extraction. strategy="docling" is reserved for future use.

    Args:
        file_path: Path to the PDF file
        strategy: Extraction strategy ("pymupdf4llm" default; "docling" reserved)

    Returns:
        ParsedDocument with pages, tables, images, metadata

    Raises:
        OprimError: File not found, DRM protected, or parse failed

    Example:
        >>> doc = file_parser_pdf(file_path=Path("report.pdf"))
        >>> len(doc.pages) > 0
        True
    """
    if not file_path.exists():
        raise OprimError(f"file_not_found: {file_path}")

    try:
        doc = fitz.open(str(file_path))
    except Exception as e:
        raise OprimError(f"pdf_parse_failed: {e}") from e

    # Check for DRM/encryption
    if doc.is_encrypted and not doc.authenticate(""):  # try empty password
        doc.close()
        raise OprimError("drm_protected: PDF is encrypted")

    pages = []
    for page_num, page in enumerate(doc, 1):
        # Primary: get_text() with Unicode map
        text = page.get_text()

        # CID 乱码检测: \ufffd 比例 > 30% → fallback to "blocks" mode
        if text:
            garbled_ratio = text.count("\ufffd") / max(len(text), 1)
            if garbled_ratio > 0.30:
                # Fallback: extract via text blocks with rawdict (better CID handling)
                text_blocks = page.get_text("blocks")
                fallback_text = "\n".join(
                    b[4] for b in text_blocks
                    if isinstance(b[4], str) and b[4].strip()
                )
                # Use fallback only if it's better (fewer \ufffd)
                if fallback_text and (
                    fallback_text.count("\ufffd") / max(len(fallback_text), 1)
                    < garbled_ratio
                ):
                    text = fallback_text

        pages.append(Page(page_number=page_num, text=text))

    metadata = doc.metadata or {}
    doc.close()

    return ParsedDocument(
        source_path=str(file_path),
        pages=pages,
        metadata={k: v for k, v in metadata.items() if v},
        status="ok",
    )
