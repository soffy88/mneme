"""Extract structural elements from a ParsedDocument."""

from __future__ import annotations

from oprim._document_types import DocumentStructure, ParsedDocument

_SENTENCE_ENDINGS = frozenset(".,:;?!")


def document_structure_extractor(*, parsed_doc: ParsedDocument) -> DocumentStructure:
    """Extract structural elements from a ParsedDocument.

    Does NOT re-parse the file. Input is the output of file_parser_*.

    Args:
        parsed_doc: Output from file_parser_pdf, file_parser_epub, etc.

    Returns:
        DocumentStructure with headings, TOC, word count

    Example:
        >>> doc = file_parser_pdf(file_path=Path("report.pdf"))
        >>> structure = document_structure_extractor(parsed_doc=doc)
        >>> len(structure.headings) >= 0
        True
    """
    headings: list[dict[str, object]] = []
    paragraphs: list[str] = []
    word_count = 0

    for page in parsed_doc.pages:
        lines = page.text.splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            word_count += len(stripped.split())
            # Heuristic: short lines (< 80 chars) that end without punctuation = heading
            if (
                len(stripped) < 80
                and stripped[-1] not in _SENTENCE_ENDINGS
                and len(stripped.split()) <= 10
            ):
                headings.append({"level": 1, "text": stripped})
            else:
                paragraphs.append(stripped)

    # Build simple TOC from headings
    toc = [{"level": h["level"], "text": h["text"]} for h in headings]

    return DocumentStructure(
        headings=headings,
        paragraphs=paragraphs[:100],  # first 100 paragraphs
        table_count=len(parsed_doc.tables),
        image_count=len(parsed_doc.images),
        word_count=word_count,
        toc=toc,
    )
