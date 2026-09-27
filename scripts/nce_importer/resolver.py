"""CanonicalVocabularyResolver.

Resolves normalized lexical forms to the single canonical VocabularyItem
authority. Existing items are reused by (language, normalized_form); new
items are created only when absent, reusing the exact K12 stable VID
algorithm (uuid5 over the DNS namespace with "en:" + normalized_form).
No second vocabulary namespace is ever created.
"""

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import VocabularyItem

# Exact reuse of the K12 importer's stable VID namespace (scripts/import_english_k12_vocab.py).
MNEME_ENGLISH_VOCAB_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def get_vid(normalized_form: str) -> str:
    return str(uuid.uuid5(MNEME_ENGLISH_VOCAB_NAMESPACE, "en:" + normalized_form))


@dataclass
class ResolvedVocab:
    normalized_form: str
    lexeme_type: str
    vocabulary_item_id: str
    is_new: bool
    display_form: str


class CanonicalVocabularyResolver:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._existing: Dict[str, str] = {}  # normalized_form -> id
        self._phrases: Set[str] = set()
        self._loaded = False

    async def ensure_loaded(self) -> None:
        if self._loaded:
            return
        rows = (
            await self._db.execute(
                select(
                    VocabularyItem.id,
                    VocabularyItem.normalized_form,
                    VocabularyItem.lexeme_type,
                ).where(VocabularyItem.language == "en")
            )
        ).all()
        for vid, norm, lex_type in rows:
            if norm:
                self._existing[norm] = vid
                if lex_type == "PHRASE":
                    self._phrases.add(norm)
        self._loaded = True

    @property
    def existing_phrases(self) -> Set[str]:
        return self._phrases

    def existing(self, normalized_form: str) -> Optional[str]:
        return self._existing.get(normalized_form)

    async def resolve(
        self, normalized_form: str, lexeme_type: str, display_form: str
    ) -> ResolvedVocab:
        await self.ensure_loaded()
        existing_id = self._existing.get(normalized_form)
        if existing_id:
            return ResolvedVocab(
                normalized_form=normalized_form,
                lexeme_type=lexeme_type,
                vocabulary_item_id=existing_id,
                is_new=False,
                display_form=display_form,
            )
        vid = get_vid(normalized_form)
        self._existing[normalized_form] = vid
        return ResolvedVocab(
            normalized_form=normalized_form,
            lexeme_type=lexeme_type,
            vocabulary_item_id=vid,
            is_new=True,
            display_form=display_form,
        )

    async def resolve_many(
        self, items: List[Tuple[str, str, str]]
    ) -> List[ResolvedVocab]:
        return [await self.resolve(nf, lt, df) for nf, lt, df in items]
