"""Pinned source manifest: NCEManifestLoader + BookManifestParser.

The manifest pins the source repository commit and the per-book resource
URLs. Resource sha256 values are recorded at fetch time (see reporter /
planner), never invented here.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .fetch import ResourceFetcher

DEFAULT_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pinned_manifest.json"
)

NCE_SCOPE = "NCE"
NCE_SERIES = "NEW_CONCEPT_ENGLISH"
NCE_COURSE_TITLE = "New Concept English"


@dataclass
class BookManifest:
    book_key: str
    edition: str
    book_resource_url: str
    book_json_url: str
    audio_url: str
    lrc_url: str
    resource_sha256: Dict[str, str] = field(default_factory=dict)


@dataclass
class SourceManifest:
    source_repository: str
    source_commit: str
    source_manifest_url: str
    parser_version: str
    code_license: str
    content_rights: str
    redistribution_allowed: bool
    rights_note: str
    books: List[BookManifest]

    @property
    def pinned(self) -> bool:
        return bool(self.source_repository and self.source_commit)


class NCEManifestLoader:
    """Loads the pinned manifest from disk (or an explicit path/URL)."""

    def __init__(self, fetcher: Optional[ResourceFetcher] = None) -> None:
        self._fetcher = fetcher

    def load(self, manifest_path: Optional[str] = None) -> SourceManifest:
        path = manifest_path or DEFAULT_MANIFEST_PATH
        if path.startswith("http://") or path.startswith("https://"):
            if self._fetcher is None:
                raise RuntimeError("RESOURCE_UNAVAILABLE: manifest URL needs a fetcher")
            res = self._fetcher.fetch_one(path)
            data = json.loads(res.body.decode("utf-8"))
        else:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        return self.parse(data)

    def parse(self, data: dict) -> SourceManifest:
        books = [
            BookManifest(
                book_key=b["book_key"],
                edition=b["edition"],
                book_resource_url=b["book_resource_url"],
                book_json_url=b["book_json_url"],
                audio_url=b["audio_url"],
                lrc_url=b["lrc_url"],
                resource_sha256=b.get("resource_sha256", {}) or {},
            )
            for b in data["books"]
        ]
        return SourceManifest(
            source_repository=data["source_repository"],
            source_commit=data["source_commit"],
            source_manifest_url=data.get("source_manifest_url", ""),
            parser_version=data.get("parser_version", ""),
            code_license=data.get("code_license", ""),
            content_rights=data.get("content_rights", ""),
            redistribution_allowed=bool(data.get("redistribution_allowed", False)),
            rights_note=data.get("rights_note", ""),
            books=books,
        )


@dataclass
class BookUnit:
    title: str
    filename: str
    source_order: int


@dataclass
class ParsedBookManifest:
    book_key: str
    edition: str
    name: str
    level: str
    cover: str
    units: List[BookUnit]
    book_json_sha256: str
    book_json_size: int


class BookManifestParser:
    """Fetches and parses {book_json_url} → units (lessons)."""

    def __init__(self, fetcher: ResourceFetcher) -> None:
        self._fetcher = fetcher

    async def parse(self, book: BookManifest) -> ParsedBookManifest:
        res = await self._fetcher.fetch_one(book.book_json_url)
        data = json.loads(res.body.decode("utf-8"))
        units_raw = data.get("units", []) or []
        units = [
            BookUnit(
                title=u.get("title") or f"Unit {idx + 1}",
                filename=u["filename"],
                source_order=idx + 1,
            )
            for idx, u in enumerate(units_raw)
            if u.get("filename")
        ]
        return ParsedBookManifest(
            book_key=book.book_key,
            edition=book.edition,
            name=data.get("name") or book.book_key,
            level=data.get("level") or "",
            cover=data.get("cover") or "",
            units=units,
            book_json_sha256=res.sha256,
            book_json_size=res.size_bytes,
        )
