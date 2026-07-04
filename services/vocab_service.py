"""vocab_service.py — 英语词汇 FSRS 复现服务（U.19 英语习得型范式）

3O 边界：接请求 → 鉴权 → 查 vocabulary_items/KCMastery → 调既有
process_interaction（复用通用字符串 knowledge_point 机制，不新建调度表）。

knowledge_point 约定：f"vocab-{VocabularyItem.id}"。到期判定复用既有
oprim.due_compute（同 review_service 对数学 KU 的到期语义）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.learner_model import GATE
from services.models import KCMastery, VocabularyItem

_VOCAB_KP_PREFIX = "vocab-"


def _kp(vocab_id: str) -> str:
    return f"{_VOCAB_KP_PREFIX}{vocab_id}"


async def get_due_vocab_reviews(
    db: AsyncSession, student_id: uuid.UUID, limit: int = 10
) -> dict:
    """取到期复现词 + 补新词（到期不足 limit 时，按频率档从低到高补未学过的词）。

    Returns
    -------
    dict
        {"due_reviews": [...], "new_words": [...]}；每项含 vocab_id/word/pos/
        meaning_cn/example_sentence/frequency_band。
    """
    from datetime import datetime, timezone

    from oprim import due_compute

    now = datetime.now(timezone.utc)

    existing_rows = (
        (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point.like(f"{_VOCAB_KP_PREFIX}%"),
                )
            )
        )
        .scalars()
        .all()
    )

    learned_vocab_ids = {
        m.knowledge_point[len(_VOCAB_KP_PREFIX) :] for m in existing_rows
    }
    due_vocab_ids = [
        m.knowledge_point[len(_VOCAB_KP_PREFIX) :]
        for m in existing_rows
        if m.fsrs_card_json and due_compute(card_dict=m.fsrs_card_json, now=now)
    ][:limit]

    due_reviews = []
    if due_vocab_ids:
        items = (
            (
                await db.execute(
                    select(VocabularyItem).where(VocabularyItem.id.in_(due_vocab_ids))
                )
            )
            .scalars()
            .all()
        )
        due_reviews = [_serialize_vocab_item(v) for v in items]

    new_words = []
    remaining = limit - len(due_reviews)
    if remaining > 0:
        query = select(VocabularyItem).order_by(
            VocabularyItem.frequency_band, VocabularyItem.frequency_rank
        )
        if learned_vocab_ids:
            query = query.where(VocabularyItem.id.notin_(learned_vocab_ids))
        candidates = (await db.execute(query.limit(remaining))).scalars().all()
        new_words = [_serialize_vocab_item(v) for v in candidates]

    return {"due_reviews": due_reviews, "new_words": new_words}


def _serialize_vocab_item(v: VocabularyItem) -> dict:
    return {
        "vocab_id": v.id,
        "word": v.word,
        "pos": v.pos,
        "meaning_cn": v.meaning_cn,
        "example_sentence": v.example_sentence,
        "frequency_band": v.frequency_band,
    }


async def submit_vocab_review(
    db: AsyncSession, student_id: uuid.UUID, vocab_id: str, remembered: bool
) -> dict:
    """提交一次词汇闪卡复现结果，回写 process_interaction（BKT+FSRS 通用管线）。"""
    exists = (
        await db.execute(select(VocabularyItem.id).where(VocabularyItem.id == vocab_id))
    ).scalar_one_or_none()
    if exists is None:
        return {"error": "词汇不存在"}

    from services.cognitive_service import process_interaction

    result = await process_interaction(
        db,
        student_id=student_id,
        kc_id=_kp(vocab_id),
        is_correct=remembered,
        question_type="vocab_flashcard",
        source="vocab_review",
    )
    await db.commit()

    return {
        "vocab_id": vocab_id,
        "remembered": remembered,
        "p_mastery": result.get("p_mastery"),
    }


async def estimate_reading_level(
    db: AsyncSession, student_id: uuid.UUID, gate: float = GATE
) -> int:
    """按学生词汇掌握度估计当前阅读水平（供分级泛读 i+1 对齐）。

    取"掌握比例(p_mastery>=gate) >= 70%"的最高频率档；无数据时默认最低档 1
    （新手起步，不假设已有水平）。
    """
    mastery_rows = (
        await db.execute(
            select(KCMastery.knowledge_point, KCMastery.p_mastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point.like(f"{_VOCAB_KP_PREFIX}%"),
            )
        )
    ).all()
    if not mastery_rows:
        return 1

    vocab_ids = [kp[len(_VOCAB_KP_PREFIX) :] for kp, _ in mastery_rows]
    band_rows = (
        await db.execute(
            select(VocabularyItem.id, VocabularyItem.frequency_band).where(
                VocabularyItem.id.in_(vocab_ids)
            )
        )
    ).all()
    band_by_id: dict[str, int] = {row[0]: row[1] for row in band_rows}

    from collections import defaultdict

    band_total: dict[int, int] = defaultdict(int)
    band_mastered: dict[int, int] = defaultdict(int)
    for kp, p_mastery in mastery_rows:
        vocab_id = kp[len(_VOCAB_KP_PREFIX) :]
        band = band_by_id.get(vocab_id)
        if band is None:
            continue
        band_total[band] += 1
        if (p_mastery or 0.0) >= gate:
            band_mastered[band] += 1

    if not band_total:
        return 1

    level = 1
    for band in sorted(band_total):
        ratio = band_mastered[band] / band_total[band]
        if ratio >= 0.7:
            level = band
        else:
            break
    return level


__all__ = [
    "get_due_vocab_reviews",
    "submit_vocab_review",
    "estimate_reading_level",
]
