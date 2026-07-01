"""PDF parser with provider dispatch."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import fitz
import pymupdf4llm

from oprim._logging import log as olog
from oprim.errors import PDFParseError


@dataclass
class ParsedContent:
    markdown: str
    plaintext: str
    page_count: int
    images: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    parser_name: str = ""
    parse_quality_score: float = 0.0


class PDFParser(Protocol):
    def parse(self, path: Path, hint: dict | None = None) -> ParsedContent: ...


def _dispatch(path: Path, hint: dict | None) -> str:
    """Choose a parser based on PDF features."""
    from oprim.classifier.detect_pdf_features import detect_pdf_features

    features = detect_pdf_features(path)
    if hint and hint.get("language") == "zh" and features.has_cjk:
        return "mineru"
    elif features.is_scanned:
        return "marker"
    else:
        return "pymupdf4llm"


def parse_pdf(
    path: Path,
    provider: str = "auto",
    hint: dict | None = None,
    embed_images: bool = False,
) -> ParsedContent:
    """Parse a PDF file and return structured content.

    Args:
        path: Path to the PDF file.
        provider: One of "auto", "pymupdf4llm", "marker", "mineru".
        hint: Optional dict with hints (e.g. {"language": "zh"}).
        embed_images: 是否将图片转为 base64 嵌入 markdown（默认 False）。
            True 时 md 体积可能增大 20x+，适合需要图片内容的场景（如数学图表）。

    Raises:
        FileNotFoundError: file does not exist.
        PDFParseError: parsing failed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if provider == "auto":
        provider = _dispatch(path, hint)

    if provider == "pymupdf4llm":
        return _parse_pymupdf4llm(path, embed_images=embed_images)
    elif provider == "marker":
        return _parse_marker(path)
    elif provider == "mineru":
        return _parse_mineru(path)
    else:
        raise PDFParseError(f"Unknown PDF provider: {provider}")


def _parse_pymupdf4llm(path: Path, *, embed_images: bool = False) -> ParsedContent:
    try:
        doc = fitz.open(str(path))
        if doc.is_encrypted:
            doc.close()
            raise PDFParseError(f"PDF is encrypted: {path}")
        page_count = len(doc)

        # TOC / chapters
        toc = doc.get_toc()
        chapters = [{"title": t[1], "page": t[2], "level": t[0]} for t in toc]

        # Tables (first 10 pages)
        tables: list[dict] = []
        for i in range(min(10, page_count)):
            try:
                result = doc[i].find_tables()
                for t in result.tables:
                    tables.append(
                        {"page": i + 1, "rows": len(t.rows), "cols": len(t.header.cells)}
                    )
            except Exception:
                pass

        metadata = dict(doc.metadata) if doc.metadata else {}
        doc.close()

        md = pymupdf4llm.to_markdown(str(path), embed_images=embed_images)
        plaintext = _md_to_plain(md)

        expected = page_count * 300
        score = min(1.0, len(md) / max(expected, 1))

        return ParsedContent(
            markdown=md,
            plaintext=plaintext,
            page_count=page_count,
            tables=tables,
            chapters=chapters,
            metadata=metadata,
            parser_name="pymupdf4llm",
            parse_quality_score=score,
        )
    except PDFParseError:
        raise
    except Exception as e:
        olog.error("pymupdf4llm parse failed", path=str(path), error=str(e))
        raise PDFParseError(f"pymupdf4llm failed for {path}: {e}") from e


def _parse_marker(path: Path) -> ParsedContent:
    """Parse with marker-pdf; falls back to pymupdf4llm if not installed."""
    try:
        from marker.convert import convert_single_pdf  # type: ignore[import]
        from marker.models import load_all_models  # type: ignore[import]

        models = load_all_models()
        full_text, images, metadata = convert_single_pdf(str(path), models)
        plaintext = _md_to_plain(full_text)
        doc = fitz.open(str(path))
        page_count = len(doc)
        doc.close()
        return ParsedContent(
            markdown=full_text,
            plaintext=plaintext,
            page_count=page_count,
            metadata=metadata or {},
            parser_name="marker",
            parse_quality_score=0.8,
        )
    except ImportError:
        olog.warning("marker-pdf not installed, falling back to pymupdf4llm")
        return _parse_pymupdf4llm(path)
    except Exception as e:
        olog.error("marker parse failed", path=str(path), error=str(e))
        raise PDFParseError(f"marker failed for {path}: {e}") from e


def _parse_mineru(path: Path) -> ParsedContent:
    """Parse with MinerU; falls back to marker (→ pymupdf4llm) if not installed."""
    try:
        import magic_pdf  # type: ignore[import]  # noqa: F401

        raise NotImplementedError("mineru path not fully implemented")
    except ImportError:
        olog.warning("mineru unavailable, fallback to marker", path=str(path))
        return _parse_marker(path)
    except Exception as e:
        olog.error("mineru parse failed", path=str(path), error=str(e))
        raise PDFParseError(f"mineru failed for {path}: {e}") from e


def _md_to_plain(md: str) -> str:
    plain = re.sub(r"#{1,6}\s+", "", md)
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", plain)
    plain = re.sub(r"\*(.+?)\*", r"\1", plain)
    plain = re.sub(r"```.*?```", "", plain, flags=re.DOTALL)
    plain = re.sub(r"`(.+?)`", r"\1", plain)
    return plain.strip()
