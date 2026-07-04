"""mastery_gate_service.py — U.17 掌握裁决题池物理隔离

3O 边界判断：编排 oskill.variant_for_review（现场生成+内核核验）+ 持久化，
与 review_service 同级的服务层业务事务，不提升为 omodul（无跨产品复用需求）。

设计（对照《善学记·教育架构完整设计》L3 评审 + 用户 2026-07-04 批准）：
BKT p_mastery 持续由日常练习/复习更新（算法状态不动，红线保留）；"掌握裁决"是叠加在
其上的独立确认状态（mastery_confirmed），只由本模块现场生成的题目判定——该题**从不
落库、不进入 wrong_questions/练习池/复习队列**，学生无法靠刷题背答案污染裁决结果。
裁决题答案缓存在 Redis（短 TTL，仅供本次判分核对），从不写入任何持久化题库表。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from obase.config import settings
from oskill import variant_for_review, ReviewVariantInput
from oprim.answer_judge import judge_answer
from services.learner_model import MASTERED
from services.models import KCMastery, WrongQuestion

_GATE_ANSWER_TTL = 1800  # 30 分钟内完成裁决作答


def _gate_answer_key(student_id: uuid.UUID, ku_id: str) -> str:
    return f"mastery_gate_answer:{student_id}:{ku_id}"


async def _get_redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def start_gate_check(
    db: AsyncSession, student_id: uuid.UUID, ku_id: str, *, caller=None
) -> dict:
    """发起一次掌握裁决：现场生成一道内核核验题（不落库）。

    返回 {eligible, reason?, already_confirmed?, item?}。**从不返回答案**。
    """
    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == ku_id,
            )
        )
    ).scalar_one_or_none()

    if row is None or (row.p_mastery or 0.0) < MASTERED:
        return {
            "eligible": False,
            "reason": f"尚未达到掌握裁决门槛（p_mastery<{MASTERED}）",
        }

    if row.mastery_confirmed:
        return {
            "eligible": True,
            "already_confirmed": True,
            "confirmed_at": row.mastery_confirmed_at.isoformat()
            if row.mastery_confirmed_at
            else None,
        }

    wq = (
        await db.execute(
            select(WrongQuestion)
            .where(WrongQuestion.knowledge_points.has_key(ku_id))
            .where(WrongQuestion.correct_answer.is_not(None))
            .limit(1)
        )
    ).scalar_one_or_none()
    if wq is None:
        return {
            "eligible": False,
            "reason": "该知识点暂无可裁决题目（需要至少一道相关题目作为出题基础）",
        }

    if caller is None:
        from obase.provider_registry import ProviderRegistry

        caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None

    variant = await variant_for_review(
        ReviewVariantInput(
            student_id=str(student_id),
            kc_id=ku_id,
            original_question=wq.question_text or "",
            original_answer=wq.correct_answer or "",
        ),
        caller=caller,
    )
    if not (variant.kernel_verified and variant.answer and variant.question):
        return {
            "eligible": False,
            "reason": "暂无法生成内核核验的裁决题（该知识点缺乏确定性求解覆盖）",
        }

    r = await _get_redis()
    try:
        await r.set(
            _gate_answer_key(student_id, ku_id), variant.answer, ex=_GATE_ANSWER_TTL
        )
    finally:
        await r.aclose()

    return {
        "eligible": True,
        "already_confirmed": False,
        "item": {"ku_id": ku_id, "question": variant.question},
    }


async def submit_gate_check(
    db: AsyncSession, student_id: uuid.UUID, ku_id: str, student_answer: str
) -> dict:
    """提交裁决作答。答对 → mastery_confirmed=True（不改动 BKT p_mastery）。"""
    r = await _get_redis()
    try:
        cached_answer = await r.get(_gate_answer_key(student_id, ku_id))
    finally:
        await r.aclose()

    if not cached_answer:
        return {"status": "expired", "message": "裁决题已过期，请重新开始"}

    verdict = judge_answer(student_answer, cached_answer).get("verdict", "unsure")

    if verdict == "correct":
        now = datetime.now(timezone.utc)
        await db.execute(
            update(KCMastery)
            .where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == ku_id,
            )
            .values(mastery_confirmed=True, mastery_confirmed_at=now)
        )
        await db.commit()

    row = (
        await db.execute(
            select(KCMastery.mastery_confirmed).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == ku_id,
            )
        )
    ).scalar_one_or_none()

    return {"status": "ok", "verdict": verdict, "mastery_confirmed": bool(row)}
