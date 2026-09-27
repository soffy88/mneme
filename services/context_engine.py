"""ContextEngine — textbook + NCE context retrieval and ranking.

Responsibilities (SPEC §52):
    get_textbook_contexts(vocab) / get_nce_contexts(vocab) /
    rank_contexts(user, vocab) / avoid_recent_repetition()

NCE context path (SPEC §15):
    VocabularyItem → LessonVocabularyMembership → NCE Lesson → TimedSentence
Select at most 1–3 contexts. Textbook context always outranks NCE (SPEC §14).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    Book,
    Course,
    Lesson,
    LessonVocabularyMembership,
    TimedSentence,
    VocabularyItem,
)


@dataclass
class VocabContext:
    vocabulary_item_id: str
    sentence_id: str
    english_text: str
    chinese_text: Optional[str]
    start_ms: Optional[int]
    end_ms: Optional[int]
    audio_uri: Optional[str]
    source: str  # TEXTBOOK / NCE
    lesson_id: str
    score: float = 0.0


class ContextEngine:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_nce_contexts(
        self, vocab_id: str, limit: int = 3
    ) -> List[VocabContext]:
        """NCE real-sentence contexts for a vocab (SPEC §15)."""
        rows = (
            await self._db.execute(
                select(
                    TimedSentence.id,
                    TimedSentence.english_text,
                    TimedSentence.chinese_text,
                    TimedSentence.start_ms,
                    TimedSentence.end_ms,
                    TimedSentence.lesson_id,
                    Lesson.audio_uri,
                )
                .join(
                    LessonVocabularyMembership,
                    LessonVocabularyMembership.lesson_id == TimedSentence.lesson_id,
                )
                .join(Lesson, Lesson.id == TimedSentence.lesson_id)
                .join(Book, Book.id == Lesson.book_id)
                .join(Course, Course.id == Book.course_id)
                .where(
                    LessonVocabularyMembership.vocabulary_item_id == vocab_id,
                    Course.scope == "NCE",
                    TimedSentence.english_text.isnot(None),
                )
                .order_by(TimedSentence.lesson_id, TimedSentence.source_order)
                .limit(limit * 3)
            )
        ).all()
        contexts = [
            VocabContext(
                vocabulary_item_id=vocab_id,
                sentence_id=r[0],
                english_text=r[1] or "",
                chinese_text=r[2],
                start_ms=r[3],
                end_ms=r[4],
                audio_uri=r[6],
                source="NCE",
                lesson_id=r[5],
            )
            for r in rows
        ]
        return self.rank_contexts(contexts)[:limit]

    def rank_contexts(
        self, contexts: List[VocabContext], recently_seen: Optional[Set[str]] = None
    ) -> List[VocabContext]:
        """Rank contexts (SPEC §16): shorter, clearer, not recently seen."""
        recently_seen = recently_seen or set()
        for ctx in contexts:
            score = 0.0
            word_count = len(ctx.english_text.split())
            if word_count <= 8:
                score += 3.0
            elif word_count <= 15:
                score += 2.0
            else:
                score += 1.0
            if ctx.start_ms is not None and ctx.end_ms is not None:
                score += 2.0
            if ctx.sentence_id in recently_seen:
                score -= 10.0
            ctx.score = score
        return sorted(contexts, key=lambda c: c.score, reverse=True)

    async def get_textbook_contexts(
        self, vocab_id: str, limit: int = 3
    ) -> List[VocabContext]:
        """Textbook contexts: K12 collection memberships (no sentence data yet).

        SPEC §81: K12 currently has vocab but no sentence contexts; textbook
        context falls back to source definition. Returns empty until K12
        sentence import lands — the model already supports it.
        """
        return []
