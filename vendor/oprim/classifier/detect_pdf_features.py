"""Detect structural features of a PDF file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from oprim._logging import log as olog
from oprim.errors import PDFParseError

_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x3040, 0x30FF),   # Hiragana + Katakana
    (0x3400, 0x4DBF),   # CJK Extension A
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
]


@dataclass
class PDFFeatures:
    page_count: int
    first_page_text: str
    has_cjk: bool
    is_scanned: bool
    has_tables: bool
    is_two_column: bool


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def detect_pdf_features(path: Path, sample_chars: int = 1000) -> PDFFeatures:
    """Analyse a PDF and return structural feature flags.

    Raises:
        FileNotFoundError: path does not exist.
        PDFParseError: PDF cannot be opened or is encrypted.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise PDFParseError(f"Cannot open PDF {path}: {e}") from e

    if doc.is_encrypted:
        doc.close()
        raise PDFParseError(f"PDF is encrypted: {path}")

    page_count = len(doc)
    first_page_text = ""
    if page_count > 0:
        first_page_text = doc[0].get_text()[:sample_chars]

    # CJK detection — check first 3 pages
    all_text = ""
    for i in range(min(3, page_count)):
        all_text += doc[i].get_text()

    cjk_count = sum(1 for ch in all_text if _is_cjk(ch))
    has_cjk = len(all_text) > 0 and cjk_count / max(len(all_text), 1) > 0.10

    # Scanned heuristic: very little extractable text
    is_scanned = len(all_text.strip()) < 150

    # Table detection
    has_tables = False
    for i in range(min(3, page_count)):
        try:
            tabs = doc[i].find_tables()
            if tabs and len(tabs.tables) > 0:
                has_tables = True
                break
        except Exception:
            pass

    # Two-column heuristic: look at horizontal distribution of text block origins
    is_two_column = False
    if page_count > 0:
        page = doc[0]
        blocks = page.get_text("blocks")
        xs = [b[0] for b in blocks if b[6] == 0]  # type-0 = text
        if len(xs) >= 4:
            page_width = page.rect.width
            left = sum(1 for x in xs if x < page_width * 0.4)
            right = sum(1 for x in xs if x > page_width * 0.55)
            is_two_column = left >= 2 and right >= 2

    doc.close()
    features = PDFFeatures(
        page_count=page_count,
        first_page_text=first_page_text,
        has_cjk=has_cjk,
        is_scanned=is_scanned,
        has_tables=has_tables,
        is_two_column=is_two_column,
    )
    olog.emit("detect_pdf_features", path=str(path), features=str(features))
    return features
