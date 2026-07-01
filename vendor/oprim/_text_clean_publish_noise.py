"""oprim.text_clean_publish_noise — Remove publishing noise from markdown text."""
from __future__ import annotations
import re


# Patterns that indicate publish noise lines
_NOISE_PATTERNS = [
    r"(?i)^(all rights reserved|copyright\s+©?|\(c\)\s+\d{4})",  # copyright
    r"(?i)^(isbn|issn|doi)\s*[:\-]?\s*[\d\-X]+",                  # identifiers
    r"(?i)^(printed in|published by|first published)",             # publisher info
    r"(?i)^(www\.|http)",                                          # URLs as lines
    r"^[\s\-—_]{3,}$",                                             # dividers
    r"(?i)^(page\s+\d+|\d+\s+of\s+\d+)$",                        # page numbers
    r"(?i)^(header|footer|watermark)",                             # explicit labels
]
_COMPILED = [re.compile(p, re.MULTILINE) for p in _NOISE_PATTERNS]

# Blank page patterns (entire section is noise)
_BLANK_SECTION = re.compile(
    r"\n#{1,6}[^\n]*\n+(?:[\s\n]*)\n(?=#{1,6}|\Z)", re.MULTILINE
)


def text_clean_publish_noise(text: str) -> str:
    """Remove publishing noise from markdown text.

    Removes: copyright pages, ISBN/ISSN lines, publisher info,
    page headers/footers, watermarks, blank sections.

    Args:
        text: Markdown text to clean.

    Returns:
        Cleaned text with noise lines removed.

    Example:
        >>> clean = text_clean_publish_noise("# Chapter\\n\\nCopyright © 2024\\n\\nContent")
        >>> "Copyright" not in clean
        True
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        is_noise = any(p.match(line.strip()) for p in _COMPILED)
        if not is_noise:
            cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    # Collapse 3+ blank lines to 2
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
