"""ProgressEngine — unified progress computation (SPEC §53).

All percentages derive from a single source of truth:
    LearningEvent + KCMastery + LearningPlan + source memberships.
Every projection is rebuildable (SPEC §90). This service never becomes a
vocabulary / FSRS authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    KCMastery,
    LessonVocabularyMembership,
    UserLessonProgress,
    VocabularyCollection,
    VocabularyCollectionMembership,
)

_VOCAB_KP_PREFIX = "vocab-"


@dataclass
class ExamCoverage:
    scope: str
    total: int
    touched: int
    mastered: int

    @property
    def touched_pct(self) -> float:
        return round(self.touched / self.total * 100, 1) if self.total else 0.0

    @property
    def mastered_pct(self) -> float:
        return round(self.mastered / self.total * 100, 1) if self.total else 0.0


@dataclass
class BookProgress:
    book_id: str
    completed_lessons: int
    total_lessons: int
    vocab_mastered: int
    vocab_total: int

    @property
    def lesson_pct(self) -> float:
        return round(self.completed_lessons / self.total_lessons * 100, 1) if self.total_lessons else 0.0

    @property
    def vocab_pct(self) -> float:
        return round(self.vocab_mastered / self.vocab_total * 100, 1) if self.vocab_total else 0.0


class ProgressEngine:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def exam_coverage(self, scope: str) -> ExamCoverage:
        """Exam coverage: touched / mastered / total (SPEC §40/41)."""
        total = (
            await self._db.execute(
                select(func.count(VocabularyCollectionMembership.vocabulary_item_id))
                .join(
                    VocabularyCollection,
                    VocabularyCollection.id == VocabularyCollectionMembership.collection_id,
                )
                .where(VocabularyCollection.scope == scope)
            )
        ).scalar() or 0

        mastered = (
            await self._db.execute(
                select(func.count(func.distinct(VocabularyCollectionMembership.vocabulary_item_id)))
                .join(
                    VocabularyCollection,
                    VocabularyCollection.id == VocabularyCollectionMembership.collection_id,
                )
                .join(
                    KCMastery,
                    KCMastery.knowledge_point
                    == func.concat(_VOCAB_KP_PREFIX, VocabularyCollectionMembership.vocabulary_item_id),
                )
                .where(
                    VocabularyCollection.scope == scope,
                    KCMastery.fsrs_card_json.isnot(None),
                )
            )
        ).scalar() or 0

        touched = (
            await self._db.execute(
                select(func.count(func.distinct(VocabularyCollectionMembership.vocabulary_item_id)))
                .join(
                    VocabularyCollection,
                    VocabularyCollection.id == VocabularyCollectionMembership.collection_id,
                )
                .join(
                    KCMastery,
                    KCMastery.knowledge_point
                    == func.concat(_VOCAB_KP_PREFIX, VocabularyCollectionMembership.vocabulary_item_id),
                )
                .where(VocabularyCollection.scope == scope)
            )
        ).scalar() or 0

        return ExamCoverage(scope=scope, total=total, touched=touched, mastered=mastered)

    async def book_progress(self, book_id: str) -> BookProgress:
        """Book progress: lesson completion and vocab mastery kept separate (SPEC §39)."""
        total_lessons = (
            await self._db.execute(
                select(func.count()).select_from(LessonVocabularyMembership)
                .where(LessonVocabularyMembership.lesson_id == book_id)
            )
        ).scalar() or 0
        # book_id here is the course_books.id; count lessons via book join
        from services.models import Lesson

        total_lessons = (
            await self._db.execute(
                select(func.count(Lesson.id)).where(Lesson.book_id == book_id)
            )
        ).scalar() or 0

        completed = (
            await self._db.execute(
                select(func.count(UserLessonProgress.lesson_id)).where(
                    UserLessonProgress.lesson_id.in_(
                        select(Lesson.id).where(Lesson.book_id == book_id)
                    ),
                    UserLessonProgress.status == "completed",
                )
            )
        ).scalar() or 0

        vocab_total = (
            await self._db.execute(
                select(func.count(func.distinct(LessonVocabularyMembership.vocabulary_item_id))).where(
                    LessonVocabularyMembership.lesson_id.in_(
                        select(Lesson.id).where(Lesson.book_id == book_id)
                    )
                )
            )
        ).scalar() or 0

        vocab_mastered = (
            await self._db.execute(
                select(func.count(func.distinct(LessonVocabularyMembership.vocabulary_item_id)))
                .join(
                    KCMastery,
                    KCMastery.knowledge_point
                    == func.concat(_VOCAB_KP_PREFIX, LessonVocabularyMembership.vocabulary_item_id),
                )
                .where(
                    LessonVocabularyMembership.lesson_id.in_(
                        select(Lesson.id).where(Lesson.book_id == book_id)
                    ),
                    KCMastery.fsrs_card_json.isnot(None),
                )
            )
        ).scalar() or 0

        return BookProgress(
            book_id=book_id,
            completed_lessons=completed,
            total_lessons=total_lessons,
            vocab_mastered=vocab_mastered,
            vocab_total=vocab_total,
        )

    async def rebuild_lesson_progress(
        self, user_id: uuid.UUID, lesson_id: str
    ) -> UserLessonProgress:
        """Rebuild a lesson projection from source-of-truth (SPEC §90)."""
        vocab_ids = (
            await self._db.execute(
                select(LessonVocabularyMembership.vocabulary_item_id).where(
                    LessonVocabularyMembership.lesson_id == lesson_id
                )
            )
        ).scalars().all()

        started = 0
        mastered = 0
        for vid in vocab_ids:
            card = (
                await self._db.execute(
                    select(KCMastery.fsrs_card_json).where(
                        KCMastery.student_id == user_id,
                        KCMastery.knowledge_point == f"{_VOCAB_KP_PREFIX}{vid}",
                    )
                )
            ).scalar_one_or_none()
            if card is not None:
                started += 1
                if card.get("stability", 0) >= 21:
                    mastered += 1

        status = "completed" if vocab_ids and mastered == len(vocab_ids) else (
            "in_progress" if started > 0 else "not_started"
        )
        existing = (
            await self._db.execute(
                select(UserLessonProgress).where(
                    UserLessonProgress.user_id == user_id,
                    UserLessonProgress.lesson_id == lesson_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = UserLessonProgress(user_id=user_id, lesson_id=lesson_id)
            self._db.add(existing)
        existing.status = status
        existing.vocab_total = len(vocab_ids)
        existing.vocab_started = started
        existing.vocab_mastered = mastered
        await self._db.flush()
        return existing
