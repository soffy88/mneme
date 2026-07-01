"""oprim.structural_chunk — single MD document chunking call.

3O layer: oprim (single atomic parse, pure logic, no LLM).
Splits Markdown into semantic sections by header hierarchy.
Each chunk preserves heading context for downstream LLM extraction.
"""

from __future__ import annotations
import re


def structural_chunk(
    *,
    text: str,
    min_chars: int = 50,
    max_chars: int = 2000,
) -> list[dict]:
    """Split Markdown text into semantic chunks by header structure.

    Returns list of: {chunk_id, level, heading, content, char_count, context_path}
    context_path: ["H1 title", "H2 title", ...] breadcrumb for heading hierarchy.
    """
    if not text or not text.strip():
        return []

    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    # Find all header positions
    headers = list(header_pattern.finditer(text))

    # Build raw sections: list of (level, heading, content_text)
    raw_sections: list[tuple[int, str, str]] = []

    if not headers:
        # No headers — treat whole text as one section (level=0, heading="")
        raw_sections.append((0, "", text.strip()))
    else:
        # Text before the first header (if any)
        preamble = text[: headers[0].start()].strip()
        if preamble:
            raw_sections.append((0, "", preamble))

        for i, match in enumerate(headers):
            level = len(match.group(1))
            heading = match.group(2).strip()
            content_start = match.end()
            content_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
            content = text[content_start:content_end].strip()
            raw_sections.append((level, heading, content))

    # Track hierarchy stack: index = level-1, value = heading text
    # Level 0 (preamble) is treated specially
    context_stack: list[str] = []  # stack of (level, heading) for ancestry

    # We maintain a parallel stack of (level, heading) pairs
    level_stack: list[tuple[int, str]] = []

    chunks: list[dict] = []

    for level, heading, content in raw_sections:
        # Update context_stack based on header level
        if level == 0:
            # preamble — no heading context change
            context_path: list[str] = []
        else:
            # Pop entries from stack that are same level or deeper
            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()
            level_stack.append((level, heading))
            context_path = [h for _, h in level_stack[:-1]]  # ancestors only

        # Split oversized content at paragraph boundaries
        sub_contents = _split_at_paragraphs(content, max_chars)

        for sub in sub_contents:
            if len(sub) < min_chars:
                continue
            chunks.append(
                {
                    "level": level,
                    "heading": heading,
                    "content": sub,
                    "char_count": len(sub),
                    "context_path": list(context_path),
                }
            )

    # Assign sequential chunk_ids
    for idx, chunk in enumerate(chunks):
        chunk["chunk_id"] = f"chunk_{idx + 1:03d}"

    return chunks


def _split_at_paragraphs(text: str, max_chars: int) -> list[str]:
    """Split text at double-newline boundaries if it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    paragraphs = re.split(r"\n\n+", text)
    result: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # +2 for the double-newline separator
        addition = len(para) + (2 if current_parts else 0)
        if current_parts and current_len + addition > max_chars:
            result.append("\n\n".join(current_parts))
            current_parts = [para]
            current_len = len(para)
        else:
            current_parts.append(para)
            current_len += addition

    if current_parts:
        result.append("\n\n".join(current_parts))

    return result if result else [text]
