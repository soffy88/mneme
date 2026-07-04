"""transfer_probe_service.py — U.18 远迁移探针题池

L0 迁移率测量。与练习池物理隔离：探针题目由 oskill.variant_for_review 现场生成
（内核核验，不落库、不进 practice/generate 静态题库），只在到期复习队列里以确定性
概率混入（同 T.2 保留探针机制：sha256(学生+日期) 门，同日同生结果可复现）。

已知局限（如实标注，非隐藏假设）：现无跨 KU 组合/新情境生成能力，这里的"迁移"实为
"同 KU 新实例迁移"（near transfer：全新数字/表述，非死记硬背原题字面），不是教育文献
意义上的远迁移（far transfer：新情境/跨知识点组合）。真正的远迁移题池需要教研设计
（如何组合 KU、如何定义"新情境"），超出本次工程范围，见 TASKS.md U.18 备注。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta, datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.config import settings
from oskill import variant_for_review, ReviewVariantInput
from services.learner_model import MASTERED
from services.models import (
    InteractionEvent,
    InteractionSource,
    KCMastery,
    WrongQuestion,
)

_PROBE_RATE_DENOMINATOR = 20  # 同 T.2 量级（约 1/20 天）
_PROBE_RECENT_DAYS = 14  # 比留存探针间隔更长——多一次 LLM+kernel 调用，节流更保守
_ANSWER_TTL = 1800  # 30 分钟内完成作答


def transfer_probe_gate(student_id: uuid.UUID, on_date: date) -> bool:
    """确定性伪随机门，与 T.2 的 probe_gate 同构但盐值不同（互相独立，不会总在同一天撞在一起）。"""
    digest = hashlib.sha256(
        f"transfer_probe:{student_id}:{on_date.isoformat()}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % _PROBE_RATE_DENOMINATOR == 0


def _answer_key(student_id: uuid.UUID, ku_id: str) -> str:
    return f"transfer_probe_answer:{student_id}:{ku_id}"


async def _get_redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def cache_transfer_probe_answer(
    student_id: uuid.UUID, ku_id: str, answer: str
) -> None:
    r = await _get_redis()
    try:
        await r.set(_answer_key(student_id, ku_id), answer, ex=_ANSWER_TTL)
    finally:
        await r.aclose()


async def get_cached_transfer_probe_answer(
    student_id: uuid.UUID, ku_id: str
) -> Optional[str]:
    """只读、不消费——同 TTL 窗口内 submit/reveal 都可能各查一次（同 _review_answer_key
    的既有约定），交由 30 分钟 TTL 自然过期，不在这里主动删除。"""
    r = await _get_redis()
    try:
        return await r.get(_answer_key(student_id, ku_id))
    finally:
        await r.aclose()


async def maybe_build_transfer_probe(
    db: AsyncSession,
    student_id: uuid.UUID,
    masteries: Sequence[KCMastery],
    *,
    caller=None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """按门控概率尝试生成一道迁移探针；不满足条件（未到门/无合适 KU/生成不可核验）
    一律返回 None（优雅跳过，不强行凑数，不污染队列）。"""
    now = now or datetime.now(timezone.utc)
    if not transfer_probe_gate(student_id, now.date()):
        return None

    recent_cutoff = now - timedelta(days=_PROBE_RECENT_DAYS)
    recently_probed = {
        kc
        for (kc,) in (
            await db.execute(
                select(InteractionEvent.knowledge_point)
                .where(InteractionEvent.student_id == student_id)
                .where(InteractionEvent.source == InteractionSource.transfer_probe)
                .where(InteractionEvent.occurred_at >= recent_cutoff)
                .distinct()
            )
        ).all()
    }

    mastered = [
        m
        for m in masteries
        if (m.p_mastery or 0.0) >= MASTERED and m.knowledge_point not in recently_probed
    ]
    if not mastered:
        return None

    if caller is None:
        from obase.provider_registry import ProviderRegistry

        caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    # 按 p_mastery 降序尝试（掌握最扎实的先测迁移），第一个能生成核验题的即用。
    for m in sorted(mastered, key=lambda x: -(x.p_mastery or 0.0)):
        ku_id = m.knowledge_point
        wq = (
            await db.execute(
                select(WrongQuestion)
                .where(WrongQuestion.knowledge_points.has_key(ku_id))
                .where(WrongQuestion.correct_answer.is_not(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        if wq is None:
            continue

        variant = await variant_for_review(
            ReviewVariantInput(
                student_id=str(student_id),
                kc_id=ku_id,
                original_question=wq.question_text or "",
                original_answer=wq.correct_answer or "",
                variant_type="context_change",  # 迁移：尽量换情境而非只换数字
            ),
            caller=caller,
        )
        if variant.kernel_verified and variant.answer and variant.question:
            await cache_transfer_probe_answer(student_id, ku_id, variant.answer)
            return {
                "kc_id": ku_id,
                "variant_question": variant.question,
                "requires_retrieval": True,
                "question_id": str(wq.id),
                "is_transfer_probe": True,
            }

    return None  # 所有候选 KU 都生成不出可核验题 → 优雅跳过，不进队列
