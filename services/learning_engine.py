"""LearningEngine — unified learning session orchestration.

Responsibilities (SPEC §51):
    build_session() / select_items() / select_task() /
    score_answer() / derive_fsrs_rating() / update_mastery() / advance_progress()

FSRS updates route through cognitive_service.process_interaction (the single
FSRS authority). Vocabulary identity stays in VocabularyItem. This service
only organizes "what the student learns today and how it goes".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.learning_scoring import (
    FSRSRating,
    Score,
    TaskType,
    derive_fsrs_rating,
    score_cloze,
    score_en_to_zh,
    score_listening,
    score_spelling,
    score_zh_to_en,
)
from services.models import (
    KCMastery,
    LearningSession,
    LearningSessionItem,
    Lesson,
    LessonVocabularyMembership,
    TimedSentence,
    VocabularyItem,
)

_VOCAB_KP_PREFIX = "vocab-"


def _kp(vocab_id: str) -> str:
    return f"{_VOCAB_KP_PREFIX}{vocab_id}"


@dataclass
class SessionItem:
    vocabulary_item_id: str
    task_type: TaskType
    context_source: str
    sentence_id: Optional[str] = None
    state: str = "PENDING"


@dataclass
class BuiltSession:
    session_id: uuid.UUID
    items: List[SessionItem] = field(default_factory=list)


@dataclass
class AnswerResult:
    score: Score
    fsrs_rating: FSRSRating
    detail: str = ""


class LearningEngine:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ---------- item selection ----------

    async def get_lesson_vocab(self, lesson_id: str) -> List[str]:
        """Ordered lesson target vocabulary (SPEC §8)."""
        rows = (
            await self._db.execute(
                select(
                    LessonVocabularyMembership.vocabulary_item_id,
                    LessonVocabularyMembership.source_order,
                )
                .where(LessonVocabularyMembership.lesson_id == lesson_id)
                .order_by(LessonVocabularyMembership.source_order)
            )
        ).all()
        return [r[0] for r in rows]

    async def classify_vocab(
        self, student_id: uuid.UUID, vocab_ids: List[str]
    ) -> dict[str, str]:
        """Classify each vocab: NEW / LEARNING / REVIEW / MASTERED / KNOWN (SPEC §9)."""
        if not vocab_ids:
            return {}
        rows = (
            await self._db.execute(
                select(KCMastery.knowledge_point, KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point.in_([_kp(v) for v in vocab_ids]),
                )
            )
        ).all()
        state_by_kp = {r[0]: r[1] for r in rows}
        result: dict[str, str] = {}
        for vid in vocab_ids:
            card = state_by_kp.get(_kp(vid))
            if card is None:
                result[vid] = "NEW"
            elif card.get("stability", 0) >= 21:
                result[vid] = "MASTERED"
            elif card.get("due") and card["due"] <= datetime.now(timezone.utc):
                result[vid] = "REVIEW"
            else:
                result[vid] = "LEARNING"
        return result

    async def get_due_reviews(
        self, student_id: uuid.UUID, limit: int = 20
    ) -> List[str]:
        """FSRS-due vocabulary reviews (SPEC §29)."""
        from oprim import due_compute

        now = datetime.now(timezone.utc)
        rows = (
            await self._db.execute(
                select(KCMastery.knowledge_point, KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point.like(f"{_VOCAB_KP_PREFIX}%"),
                )
            )
        ).all()
        due = [kp[len(_VOCAB_KP_PREFIX):] for kp, card in rows if card and due_compute(card_dict=card, now=now)]
        return due[:limit]

    # ---------- task selection ----------

    def select_task(self, classification: str, failed_before: bool = False) -> TaskType:
        """Task selector (SPEC §21): FSRS decides WHEN, this decides HOW."""
        if classification == "NEW":
            return TaskType.EN_TO_ZH
        if classification == "LEARNING":
            return TaskType.ZH_TO_EN if not failed_before else TaskType.CONTEXT_CLOZE
        if classification == "REVIEW":
            return TaskType.CONTEXT_CLOZE
        if classification == "MASTERED":
            return TaskType.LISTENING_RECOGNITION
        return TaskType.EN_TO_ZH

    # ---------- scoring ----------

    def score_answer(
        self,
        task_type: TaskType,
        *,
        expected: str,
        answer: str,
        aliases: Optional[List[str]] = None,
        sentence: str = "",
    ) -> ScoreResult:
        if task_type == TaskType.EN_TO_ZH:
            from services.learning_scoring import ScoreResult

            return score_en_to_zh(expected, answer, aliases)
        if task_type == TaskType.ZH_TO_EN:
            return score_zh_to_en(expected, answer)
        if task_type == TaskType.SPELLING:
            return score_spelling(expected, answer)
        if task_type == TaskType.LISTENING_RECOGNITION:
            return score_listening(expected, answer)
        if task_type == TaskType.CONTEXT_CLOZE:
            return score_cloze(expected, answer, sentence)
        from services.learning_scoring import ScoreResult

        return ScoreResult(Score.INCORRECT, "unknown_task")

    # ---------- session building ----------

    async def build_lesson_session(
        self,
        student_id: uuid.UUID,
        lesson_id: str,
        *,
        learning_plan_id: Optional[uuid.UUID] = None,
        max_items: int = 25,
    ) -> BuiltSession:
        """Build a lesson session: due reviews + new + weak + NCE reinforcement (SPEC §55/57)."""
        lesson_vocab = await self.get_lesson_vocab(lesson_id)
        classification = await self.classify_vocab(student_id, lesson_vocab)
        due = await self.get_due_reviews(student_id)

        items: List[SessionItem] = []
        seen: set = set()

        # 1. due reviews (priority)
        for vid in due:
            if len(items) >= max_items:
                break
            if vid in seen:
                continue
            seen.add(vid)
            items.append(SessionItem(vid, TaskType.CONTEXT_CLOZE, "REVIEW"))

        # 2. current lesson new/learning
        for vid in lesson_vocab:
            if len(items) >= max_items:
                break
            if vid in seen:
                continue
            cls = classification.get(vid, "NEW")
            if cls in ("NEW", "LEARNING"):
                seen.add(vid)
                items.append(SessionItem(vid, self.select_task(cls), "TEXTBOOK"))

        # 3. NCE reinforcement for lesson vocab
        if len(items) < max_items:
            nce_items = await self._nce_reinforcement(seen, limit=max_items - len(items))
            items.extend(nce_items)

        session = LearningSession(
            user_id=student_id,
            learning_plan_id=learning_plan_id,
            mode="LESSON",
            lesson_id=lesson_id,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(session)
        await self._db.flush()

        for seq, item in enumerate(items, start=1):
            self._db.add(
                LearningSessionItem(
                    session_id=session.id,
                    vocabulary_item_id=item.vocabulary_item_id,
                    task_type=item.task_type.value,
                    context_source=item.context_source,
                    sentence_id=item.sentence_id,
                    sequence=seq,
                )
            )
        await self._db.flush()
        return BuiltSession(session_id=session.id, items=items)

    async def _nce_reinforcement(
        self, exclude_vocab: set, limit: int
    ) -> List[SessionItem]:
        """NCE context reinforcement: vocab in NCE lessons not already in session."""
        if limit <= 0:
            return []
        rows = (
            await self._db.execute(
                select(LessonVocabularyMembership.vocabulary_item_id)
                .where(LessonVocabularyMembership.vocabulary_item_id.notin_(list(exclude_vocab)) if exclude_vocab else True)
                .distinct()
                .limit(limit)
            )
        ).all()
        return [SessionItem(r[0], TaskType.CONTEXT_CLOZE, "NCE") for r in rows]

    # ---------- answer processing ----------

    async def submit_answer(
        self,
        session_id: uuid.UUID,
        item_sequence: int,
        *,
        answer: str,
        interaction_id: uuid.UUID,
        used_hint: bool = False,
        latency_ms: Optional[int] = None,
    ) -> AnswerResult:
        """Atomic answer processing (SPEC §70): score → LearningEvent → FSRS → progress."""
        item = (
            await self._db.execute(
                select(LearningSessionItem).where(
                    LearningSessionItem.session_id == session_id,
                    LearningSessionItem.sequence == item_sequence,
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise ValueError("session item not found")
        if item.state == "ANSWERED":
            raise ValueError("item already answered")

        vocab = (
            await self._db.execute(
                select(VocabularyItem).where(VocabularyItem.id == item.vocabulary_item_id)
            )
        ).scalar_one()
        sentence = None
        if item.sentence_id:
            sentence = (
                await self._db.execute(
                    select(TimedSentence).where(TimedSentence.id == item.sentence_id)
                )
            ).scalar_one_or_none()

        expected = vocab.meaning_cn or vocab.word
        score_result = self.score_answer(
            TaskType(item.task_type),
            expected=expected,
            answer=answer,
            sentence=sentence.english_text if sentence else "",
        )
        rating = derive_fsrs_rating(
            score_result.score, used_hint=used_hint, latency_ms=latency_ms
        )

        item.state = "ANSWERED"
        item.interaction_id = interaction_id

        session = (
            await self._db.execute(
                select(LearningSession).where(LearningSession.id == session_id)
            )
        ).scalar_one()

        from services.cognitive_service import process_interaction

        await process_interaction(
            self._db,
            student_id=session.user_id,
            kc_id=_kp(vocab.id),
            is_correct=score_result.score == Score.CORRECT,
            question_type=str(item.task_type),
            source="quick",
        )
        await self._db.flush()
        return AnswerResult(score=score_result.score, fsrs_rating=rating, detail=score_result.detail)
