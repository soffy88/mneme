"""Tantivy-based full-text search index."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import tantivy

from oprim._logging import log as olog
from oprim.errors import FulltextError


@dataclass
class FulltextDoc:
    id: str
    fields: dict[str, str]


@dataclass
class FulltextHit:
    id: str
    score: float
    highlight: str | None


class FulltextIndex(Protocol):
    def add(self, docs: list[FulltextDoc]) -> None: ...
    def search(
        self,
        query: str,
        top_k: int = 20,
        fields: list[str] | None = None,
    ) -> list[FulltextHit]: ...
    def delete(self, ids: list[str]) -> None: ...


class TantivyFulltextIndex:
    """Full-text index backed by Tantivy with id/title/content/tags fields."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.mkdir(parents=True, exist_ok=True)

        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_text_field("id", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("title", stored=True)
        schema_builder.add_text_field("content", stored=True)
        schema_builder.add_text_field("tags", stored=True)
        self._schema = schema_builder.build()

        try:
            self._index = tantivy.Index(self._schema, path=str(self._path))
        except Exception as e:
            raise FulltextError(
                f"Failed to open tantivy index at {self._path}: {e}"
            ) from e

    def add(self, docs: list[FulltextDoc]) -> None:
        try:
            writer = self._index.writer()
            for doc in docs:
                tdoc = tantivy.Document()
                tdoc.add_text("id", doc.id)
                tdoc.add_text("title", doc.fields.get("title", ""))
                tdoc.add_text("content", doc.fields.get("content", ""))
                tdoc.add_text("tags", doc.fields.get("tags", ""))
                writer.add_document(tdoc)
            writer.commit()
            self._index.reload()
            olog.emit("fulltext_add", count=len(docs))
        except Exception as e:
            olog.error("fulltext_add failed", error=str(e))
            raise FulltextError(f"Add failed: {e}") from e

    def search(
        self,
        query: str,
        top_k: int = 20,
        fields: list[str] | None = None,
    ) -> list[FulltextHit]:
        try:
            searcher = self._index.searcher()
            search_fields = fields or ["title", "content", "tags"]
            # tantivy 0.26 uses Index.parse_query(str, fields)
            parsed = self._index.parse_query(query, search_fields)
            results = searcher.search(parsed, limit=top_k)
            hits: list[FulltextHit] = []
            for score, addr in results.hits:
                retrieved = searcher.doc(addr)
                doc_id = retrieved.get_first("id") or ""
                hits.append(FulltextHit(id=doc_id, score=score, highlight=None))
            return hits
        except Exception as e:
            olog.error("fulltext_search failed", error=str(e))
            raise FulltextError(f"Search failed: {e}") from e

    def delete(self, ids: list[str]) -> None:
        try:
            writer = self._index.writer()
            for doc_id in ids:
                writer.delete_documents("id", doc_id)
            writer.commit()
            self._index.reload()
            olog.emit("fulltext_delete", count=len(ids))
        except Exception as e:
            olog.error("fulltext_delete failed", error=str(e))
            raise FulltextError(f"Delete failed: {e}") from e


def open_fulltext_index(
    path: Path, provider: str = "tantivy"
) -> TantivyFulltextIndex:
    """Open or create a full-text index at *path*.

    Raises:
        FulltextError: unknown provider.
    """
    if provider != "tantivy":
        raise FulltextError(f"Unknown fulltext provider: {provider}")
    return TantivyFulltextIndex(path)
