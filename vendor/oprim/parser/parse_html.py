"""HTML parser using trafilatura with readability-lxml fallback."""
from __future__ import annotations

import trafilatura

from oprim._logging import log as olog
from oprim.parser.parse_pdf import ParsedContent


def parse_html(
    html_content: str | bytes,
    base_url: str | None = None,
) -> ParsedContent:
    """Extract main content from an HTML document.

    Args:
        html_content: Raw HTML as string or bytes.
        base_url: Optional URL for relative link resolution / metadata.

    Returns:
        ParsedContent with markdown == plaintext == extracted text.
    """
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8", errors="replace")

    text = ""
    try:
        text = (
            trafilatura.extract(
                html_content,
                url=base_url,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
            or ""
        )
    except Exception as e:
        olog.warning("trafilatura failed, trying readability", error=str(e))
        try:
            import re

            from readability import Document  # type: ignore[import]

            doc = Document(html_content)
            text = re.sub(r"<[^>]+>", " ", doc.summary())
        except Exception as e2:
            olog.error("both html parsers failed", error=str(e2))
            text = ""

    return ParsedContent(
        markdown=text,
        plaintext=text,
        page_count=1,
        metadata={"base_url": base_url or ""},
        parser_name="trafilatura",
        parse_quality_score=0.8 if len(text) > 100 else 0.2,
    )
