"""Parse HTML content and extract structured text."""

from __future__ import annotations

import trafilatura
from bs4 import BeautifulSoup

from oprim._document_types import Page, ParsedDocument
from oprim._exceptions import OprimError


def file_parser_html(
    *,
    html_content: str,
    url: str | None = None,
) -> ParsedDocument:
    """Parse HTML content and extract structured text.

    Args:
        html_content: Raw HTML string
        url: Source URL (stored as metadata only)

    Returns:
        ParsedDocument with a single page containing the main content

    Raises:
        OprimError: Parse error
    """
    try:
        # Extract main content using trafilatura
        main_text = trafilatura.extract(html_content, url=url, include_tables=True) or ""

        # Extract metadata using bs4
        soup = BeautifulSoup(html_content, "html.parser")
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else ""

        page = Page(page_number=1, text=main_text)
        metadata: dict[str, str] = {"title": title_text}
        if url:
            metadata["url"] = url

        return ParsedDocument(
            source_path=url,
            pages=[page],
            metadata=metadata,
            status="ok",
        )
    except Exception as e:
        raise OprimError(f"html_parse_failed: {e}") from e
