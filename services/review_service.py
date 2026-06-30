from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from oprim import due_compute
from oskill import variant_for_review, ReviewVariantInput
from omodul.due_recall_push import due_recall_push_workflow, DueRecallPushConfig, DueRecallPushInput
from services.models import KCMastery, WrongQuestion
from obase.provider_registry import ProviderRegistry
from obase.persistence.pool import PgPool
from obase.config import settings

async def get_pg_pool() -> PgPool:
    dsn = settings.DATABASE_URL.replace('+asyncpg', '')
    return await PgPool.get_or_create(dsn=dsn)

async def get_due_variants(
    db: AsyncSession, student_id: uuid.UUID, *, generate_variants: bool = False
) -> List[dict]:
    """到期复习池。默认**不**逐卡同步调 LLM 生成变式（性能/稳定性）——直接发原题面
    供检索练习；generate_variants=True 才生成变式（变式纯锦上添花，非闭环必需）。"""
    # 1. Fetch all mastery for student
    stmt = select(KCMastery).where(KCMastery.student_id == student_id)
    masteries = (await db.execute(stmt)).scalars().all()

    due_items = []
    now = datetime.now(timezone.utc)

    caller = (ProviderRegistry.get().llm() if ProviderRegistry._instance else None) if generate_variants else None

    for m in masteries:
        if not m.fsrs_card_json:
            continue

        # 2. Check if due
        is_due = due_compute(card_dict=m.fsrs_card_json, now=now)
        if is_due:
            # Find an original question for context
            wq_stmt = select(WrongQuestion).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.knowledge_points.has_key(m.knowledge_point)
            ).limit(1)
            wq = (await db.execute(wq_stmt)).scalar_one_or_none()

            orig_q = wq.question_text if wq else "已知知识点为 " + m.knowledge_point
            orig_a = wq.correct_answer if wq else "无"

            # 默认走原题面（无 LLM、无 N+1 延迟）；仅在显式开启变式时调 LLM，
            # 失败也回退原题面（不丢到期项=不让"学了就忘"）。
            question_text = orig_q
            if generate_variants:
                try:
                    variant = await variant_for_review(
                        ReviewVariantInput(
                            student_id=str(student_id),
                            kc_id=m.knowledge_point,
                            original_question=orig_q,
                            original_answer=orig_a
                        ),
                        caller=caller
                    )
                    if variant and variant.question:
                        question_text = variant.question
                except Exception:
                    pass  # 用原题面兜底，不丢到期项

            # 检索练习红线（item 4）：到期复习只发题面，**不附答案**——
            # 学生必须先尝试回忆作答；答案只能经 reveal/submit 显式获取，
            # 而"看答案=放弃检索"会被 reveal 记为 FSRS Again。
            due_items.append({
                "kc_id": m.knowledge_point,
                "variant_question": question_text,
                "requires_retrieval": True,
                "due_since": m.last_interaction_at.isoformat() if m.last_interaction_at else None,
                "fsrs_interval": m.fsrs_card_json.get("stability", 0)
            })
                
    if due_items:
        # 4. Wrap with due_recall_push (omodul)
        # Note: omodul.due_recall_push_workflow might trigger actual push (e.g. Telegram)
        # Here we just use it for the "business transaction" recording if needed.
        pool = await get_pg_pool()
        await due_recall_push_workflow(
            config=DueRecallPushConfig(),
            input_data=DueRecallPushInput(
                batch_id=str(uuid.uuid4()),
                due_items=due_items
            ),
            pool=pool
        )

    return due_items


async def _original_answer_for_kc(db: AsyncSession, student_id: uuid.UUID, kc_id: str) -> str:
    """取该 kc 一条原错题的参考答案（复习核对/揭示用）。"""
    wq = (await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.student_id == student_id,
            WrongQuestion.knowledge_points.has_key(kc_id),
        ).limit(1)
    )).scalar_one_or_none()
    return (wq.correct_answer if wq else "") or ""


async def reveal_review_answer(db: AsyncSession, student_id: uuid.UUID, kc_id: str) -> dict:
    """揭示复习答案（学生放弃检索）。检索练习红线：看答案 = FSRS Again。

    记一次 used_answer=True 的交互（映射 Again，掌握度按答错衰减），再返回答案。
    """
    from services.cognitive_service import process_interaction
    answer = await _original_answer_for_kc(db, student_id, kc_id)
    await process_interaction(
        db,
        student_id=student_id,
        kc_id=kc_id,
        is_correct=False,
        question_type="solve",
        source="review",
        used_answer=True,   # 看答案 → fsrs_map_rating 返回 Again
    )
    return {"kc_id": kc_id, "answer": answer, "recorded_again": True}


async def submit_review_answer(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str, student_answer: str
) -> dict:
    """提交复习作答（先检索后核对）。确定性判分并记入 BKT/FSRS，再返回参考答案。"""
    from oprim.answer_judge import judge_answer
    from services.cognitive_service import process_interaction
    answer = await _original_answer_for_kc(db, student_id, kc_id)
    verdict = judge_answer(student_answer, answer).get("verdict", "unsure")
    # unsure（自由作答）按"未确定"不武断判错：交学生自评，这里仅在可判定时入算法
    if verdict in ("correct", "wrong"):
        await process_interaction(
            db,
            student_id=student_id,
            kc_id=kc_id,
            is_correct=(verdict == "correct"),
            question_type="solve",
            source="review",
        )
    return {"kc_id": kc_id, "verdict": verdict, "answer": answer}
