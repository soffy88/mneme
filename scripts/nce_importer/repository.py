"""CourseImportRepository: transactional execution of a CourseImportPlan.

Upsert order: course → books → lessons → timed_sentences → new canonical
vocabulary → lesson vocabulary memberships → sentence occurrences.
All ids are stable uuid5, so a second apply is a no-op (idempotent).
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, List

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    Course,
    Book,
    Lesson,
    TimedSentence,
    LessonVocabularyMembership,
    SentenceVocabularyOccurrence,
    VocabularyItem,
)

from .planner import CourseImportPlan, PlannedOccurrence


@dataclass
class RepositoryStats:
    courses_upserted: int = 0
    books_upserted: int = 0
    lessons_upserted: int = 0
    sentences_upserted: int = 0
    vocab_created: int = 0
    vocab_existing: int = 0
    memberships_upserted: int = 0
    occurrences_upserted: int = 0


def _lesson_id(book_id: str, lesson_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mneme://lesson/{book_id}/{lesson_key}"))


def _sentence_id(lesson_id: str, source_entry_key: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"mneme://sentence/{lesson_id}/{source_entry_key}"
        )
    )


def _membership_id(lesson_id: str, vocabulary_item_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mneme://lesson-vocab/{lesson_id}/{vocabulary_item_id}",
        )
    )


def _occurrence_id(
    sentence_id: str, vocabulary_item_id: str, occurrence_index: int
) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"mneme://sentence-vocab/{sentence_id}/{vocabulary_item_id}/{occurrence_index}",
        )
    )


class CourseImportRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.stats = RepositoryStats()

    async def execute(self, plan: CourseImportPlan) -> RepositoryStats:
        await self._upsert_course(plan)
        lesson_ctx: List[tuple] = []
        for book in plan.books:
            book_id = await self._upsert_book(plan, book)
            for lesson in book.lessons:
                lesson_id = await self._upsert_lesson(book_id, lesson)
                sentence_ids = await self._upsert_sentences(lesson_id, lesson)
                lesson_ctx.append((lesson_id, lesson, sentence_ids))

        # Vocabulary must exist before memberships/occurrences (FK).
        await self._upsert_vocab(plan)

        new_vocab_ids = {v.vocabulary_item_id for v in plan.new_vocab}
        for lesson_id, lesson, sentence_ids in lesson_ctx:
            await self._upsert_memberships(lesson_id, lesson, sentence_ids, new_vocab_ids)
            await self._upsert_occurrences(lesson, sentence_ids)
        return self.stats

    async def _upsert_course(self, plan: CourseImportPlan) -> None:
        stmt = (
            insert(Course)
            .values(
                id=plan.course_id,
                scope=plan.scope,
                series=plan.series,
                title=plan.title,
                source_id=plan.source_id,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self._db.execute(stmt)
        self.stats.courses_upserted += 1

    async def _upsert_book(self, plan: CourseImportPlan, book) -> str:
        book_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"mneme://book/{plan.scope}/{plan.series}/{book.edition}/{book.book_key}",
            )
        )
        stmt = (
            insert(Book)
            .values(
                id=book_id,
                course_id=plan.course_id,
                book_key=book.book_key,
                title=book.title,
                level=book.level,
                edition=book.edition,
                source_url=book.source_url,
                source_hash=book.source_hash,
                source_metadata=book.source_metadata,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self._db.execute(stmt)
        self.stats.books_upserted += 1
        return book_id

    async def _upsert_lesson(self, book_id: str, lesson) -> str:
        lesson_id = _lesson_id(book_id, lesson.lesson_key)
        stmt = (
            insert(Lesson)
            .values(
                id=lesson_id,
                book_id=book_id,
                lesson_key=lesson.lesson_key,
                title=lesson.title,
                source_order=lesson.source_order,
                audio_uri=lesson.audio_uri,
                audio_hash=lesson.audio_hash,
                audio_duration_ms=lesson.audio_duration_ms,
                lrc_uri=lesson.lrc_uri,
                lrc_hash=lesson.lrc_hash,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await self._db.execute(stmt)
        self.stats.lessons_upserted += 1
        return lesson_id

    async def _upsert_sentences(
        self, lesson_id: str, lesson
    ) -> Dict[str, str]:
        sentence_ids: Dict[str, str] = {}
        for sent in lesson.sentences:
            sent_id = _sentence_id(lesson_id, sent.source_entry_key)
            stmt = (
                insert(TimedSentence)
                .values(
                    id=sent_id,
                    lesson_id=lesson_id,
                    source_order=sent.source_order,
                    start_ms=sent.start_ms,
                    end_ms=sent.end_ms,
                    english_text=sent.english_text,
                    chinese_text=sent.chinese_text,
                    raw_text=sent.raw_text,
                    source_line=sent.source_line,
                    source_entry_key=sent.source_entry_key,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await self._db.execute(stmt)
            self.stats.sentences_upserted += 1
            sentence_ids[sent.source_entry_key] = sent_id
        return sentence_ids

    async def _upsert_vocab(self, plan: CourseImportPlan) -> None:
        for vocab in plan.new_vocab:
            stmt = (
                insert(VocabularyItem)
                .values(
                    id=vocab.vocabulary_item_id,
                    word=vocab.display_form,
                    language="en",
                    display_form=vocab.display_form,
                    normalized_form=vocab.normalized_form,
                    lexeme_type=vocab.lexeme_type,
                    canonical_meaning=None,
                    frequency_rank=99999,
                    frequency_band=5,
                    source="nce",
                    ai_generated=False,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await self._db.execute(stmt)
            self.stats.vocab_created += 1

    async def _upsert_memberships(
        self,
        lesson_id: str,
        lesson,
        sentence_ids: Dict[str, str],
        new_vocab_ids: set,
    ) -> None:
        # Aggregate occurrences per vocabulary item: 10 occurrences in a lesson
        # → 1 membership row with occurrence_count=10.
        agg: Dict[str, dict] = {}
        for sent in lesson.sentences:
            for occ in sent.occurrences:
                entry = agg.setdefault(
                    occ.vocabulary_item_id,
                    {
                        "count": 0,
                        "first_sentence_id": None,
                        "first_occurrence_order": None,
                        "source_order": None,
                        "normalized_form": occ.normalized_form,
                    },
                )
                entry["count"] += 1
                if entry["first_sentence_id"] is None:
                    entry["first_sentence_id"] = sentence_ids[sent.source_entry_key]
                    entry["first_occurrence_order"] = occ.occurrence_index
                    entry["source_order"] = sent.source_order

        for vid, entry in agg.items():
            if vid not in new_vocab_ids:
                self.stats.vocab_existing += 1
            stmt = (
                insert(LessonVocabularyMembership)
                .values(
                    id=_membership_id(lesson_id, vid),
                    lesson_id=lesson_id,
                    vocabulary_item_id=vid,
                    first_sentence_id=entry["first_sentence_id"],
                    first_occurrence_order=entry["first_occurrence_order"],
                    occurrence_count=entry["count"],
                    source_order=entry["source_order"],
                )
                .on_conflict_do_nothing(constraint="uq_lesson_vocab")
            )
            await self._db.execute(stmt)
            self.stats.memberships_upserted += 1

    async def _upsert_occurrences(
        self, lesson, sentence_ids: Dict[str, str]
    ) -> None:
        for sent in lesson.sentences:
            sent_id = sentence_ids[sent.source_entry_key]
            per_vocab_index: Dict[str, int] = {}
            for occ in sent.occurrences:
                idx = per_vocab_index.get(occ.vocabulary_item_id, 0)
                per_vocab_index[occ.vocabulary_item_id] = idx + 1
                stmt = (
                    insert(SentenceVocabularyOccurrence)
                    .values(
                        id=_occurrence_id(sent_id, occ.vocabulary_item_id, idx),
                        sentence_id=sent_id,
                        vocabulary_item_id=occ.vocabulary_item_id,
                        occurrence_index=idx,
                        token_start=occ.token_start,
                        token_end=occ.token_end,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_sentence_vocab_occurrence"
                    )
                )
                await self._db.execute(stmt)
                self.stats.occurrences_upserted += 1
