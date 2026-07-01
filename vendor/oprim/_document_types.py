from __future__ import annotations

from pydantic import BaseModel


class Page(BaseModel):
    page_number: int
    text: str
    tables: list[dict[str, object]] = []


class Table(BaseModel):
    caption: str | None = None
    headers: list[str] = []
    rows: list[list[str]] = []


class ImageRef(BaseModel):
    index: int
    caption: str | None = None
    alt_text: str | None = None


class ParsedDocument(BaseModel):
    source_path: str | None = None
    pages: list[Page] = []
    tables: list[Table] = []
    images: list[ImageRef] = []
    metadata: dict[str, str] = {}
    status: str = "ok"  # "ok" | "drm_protected" | "parse_failed"


class Section(BaseModel):
    title: str
    level: int  # 1=H1, 2=H2, etc.
    content: str


class ParsedMarkdown(BaseModel):
    source_path: str
    frontmatter: dict[str, object] = {}
    sections: list[Section] = []
    body: str = ""
    title: str | None = None


class ParsedPlaintext(BaseModel):
    source_path: str
    encoding: str
    paragraphs: list[str] = []
    line_count: int = 0
    language_hint: str | None = None


class DocumentStructure(BaseModel):
    headings: list[dict[str, object]] = []  # [{"level": 1, "text": "Title"}, ...]
    paragraphs: list[str] = []
    table_count: int = 0
    image_count: int = 0
    word_count: int = 0
    toc: list[dict[str, object]] = []  # table of contents
