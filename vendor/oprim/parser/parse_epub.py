"""EPUB parser using ebooklib."""
from __future__ import annotations

import re
from pathlib import Path

import ebooklib
from ebooklib import epub

from oprim._logging import log as olog
from oprim.parser.parse_pdf import ParsedContent


def parse_epub(path: Path) -> ParsedContent:
    """Parse an EPUB file and return structured content.

    Raises:
        FileNotFoundError: file does not exist.
        Exception: propagated from ebooklib on parse failure.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        book = epub.read_epub(str(path))
        chapters = []
        all_md: list[str] = []
        # Build TOC title map: file_name → semantic title
        toc_map: dict[str, str] = {}
        def _walk_toc(nodes):
            for node in nodes:
                if hasattr(node, "href") and hasattr(node, "title"):
                    toc_map[node.href.split("#")[0]] = node.title
                if hasattr(node, "__iter__") and not hasattr(node, "href"):
                    _walk_toc(node)
        _walk_toc(book.toc)

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content().decode("utf-8", errors="replace")
            plain = re.sub(r"<[^>]+>", " ", content)
            plain = re.sub(r"\s+", " ", plain).strip()
            # Use TOC semantic title if available, fall back to file name
            title = toc_map.get(item.get_name(), item.get_name())
            chapters.append({"title": title, "content_len": len(plain)})
            all_md.append(f"## {title}\n\n{plain}")

        markdown = "\n\n".join(all_md)
        plaintext = re.sub(r"#{1,6}\s+", "", markdown)

        return ParsedContent(
            markdown=markdown,
            plaintext=plaintext,
            page_count=len(chapters),
            chapters=chapters,
            metadata={
                "title": book.title or "",
                "author": ", ".join(
                    str(v[0][0]) for v in [book.get_metadata("DC", "creator")]
                    if v
                ) or "",
                "language": (book.get_metadata("DC", "language") or [("",)])[0][0] or "",
            },
            parser_name="ebooklib",
            parse_quality_score=0.8 if chapters else 0.1,
        )
    except Exception as e:
        olog.error("parse_epub failed", path=str(path), error=str(e))
        raise
