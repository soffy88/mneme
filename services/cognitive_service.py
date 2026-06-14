"""
Cognitive service — Layer 4 装配层
接 process_interaction / mastery_overview / review_queue，
调 omodul/oskill/oprim，不写业务逻辑。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from obase.cognitive_store import PgStore
from omodul.cognitive import (
    InteractionConfig,
    InteractionInput,
    mastery_overview_workflow,
    process_interaction_workflow,
    review_queue_workflow,
)
from oprim.compute_feedback import compute_feedback
from oprim.compute_peer_percentile import compute_peer_percentile
from oskill.interleave_select import QuestionItem, interleave_select

from services.models import KCMastery, MasterySnapshot


async def process_interaction(
    db: AsyncSession,
    student_id: UUID,
    kc_id: str,
    is_correct: bool,
    *,
    question_type: str = "solve",
    question_id: Optional[UUID] = None,
    source: str = "paper",
    used_answer: bool = False,
    struggled: bool = False,
    effortless: bool = False,
    is_interleaved: bool = False,
    time_spent_seconds: Optional[int] = None,
    student_answer: Optional[str] = None,
    correct_answer: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """处理一次答题交互，落 kc_mastery + interaction_events + mastery_snapshots。"""
    now = now or datetime.now(timezone.utc)
    store = PgStore(db)
    config = InteractionConfig()
    input_data = InteractionInput(
        student_id=student_id,
        kc_id=kc_id,
        is_correct=is_correct,
        question_type=question_type,
        question_id=question_id,
        source=source,
        used_answer=used_answer,
        struggled=struggled,
        effortless=effortless,
        is_interleaved=is_interleaved,
        time_spent_seconds=time_spent_seconds,
        now=now,
    )
    result = await process_interaction_workflow(config, input_data, store)
    findings = result["findings"]

    # upsert 月度快照（只更新本月，不覆盖历史）
    snapshot_month = now.date().replace(day=1)
    stmt = (
        pg_insert(MasterySnapshot)
        .values(
            student_id=student_id,
            knowledge_point=kc_id,
            long_term_mastery=findings.long_term_mastery,
            dominant_error_type=findings.error_type,
            snapshot_month=snapshot_month,
        )
        .on_conflict_do_update(
            constraint="uq_mastery_snapshots_student_kc_month",
            set_={
                "long_term_mastery": findings.long_term_mastery,
                "dominant_error_type": findings.error_type,
            },
        )
    )
    await db.execute(stmt)

    feedback = None
    if student_answer is not None:
        fb = compute_feedback(student_answer, expected_answer=correct_answer)
        feedback = {"category": fb.category, "message": fb.message, "hint": fb.hint}

    return {**findings.model_dump(), "feedback": feedback}


async def mastery_overview(
    db: AsyncSession,
    student_id: UUID,
    now: Optional[datetime] = None,
) -> list[dict]:
    """返回学生所有知识点掌握度总览，按 effective_mastery 升序（薄弱在前），含百分位。"""
    now = now or datetime.now(timezone.utc)
    store = PgStore(db)
    items = await mastery_overview_workflow(store, student_id, now=now)

    # 获取所有学生在各 KC 的 effective_mastery，用于计算百分位
    # 读 kc_mastery 中各 KC 的全量 p_mastery（简化：以 p_mastery 代替 effective_mastery 做分布）
    kc_ids = [item["kc_id"] for item in items]
    peer_data: dict[str, list[float]] = {}
    if kc_ids:
        rows = (
            await db.execute(
                select(KCMastery.knowledge_point, KCMastery.p_mastery)
                .where(KCMastery.knowledge_point.in_(kc_ids))
                .where(KCMastery.p_mastery.is_not(None))
            )
        ).all()
        for kc, pm in rows:
            peer_data.setdefault(kc, []).append(pm)

    result = []
    for item in items:
        kc = item["kc_id"]
        peer_vals = peer_data.get(kc, [item["effective_mastery"]])
        try:
            pct = compute_peer_percentile(item["effective_mastery"], peer_vals)
            item = {**item, "peer_percentile": pct.percentile}
        except (ValueError, ZeroDivisionError):
            item = {**item, "peer_percentile": None}
        result.append(item)

    return result


async def review_queue(
    db: AsyncSession,
    student_id: UUID,
    now: Optional[datetime] = None,
) -> list[dict]:
    """返回今日复习队列，经 interleave_select 排布（相邻题 KC 不同）。"""
    now = now or datetime.now(timezone.utc)
    store = PgStore(db)
    raw = await review_queue_workflow(store, student_id, now=now)

    if not raw:
        return []

    # 从 kc_mastery 取各 KC 的掌握度，用于 interleave 优先级
    kc_ids = [item["kc_id"] for item in raw]
    mastery_rows = (
        await db.execute(
            select(KCMastery.knowledge_point, KCMastery.p_mastery)
            .where(KCMastery.student_id == student_id)
            .where(KCMastery.knowledge_point.in_(kc_ids))
        )
    ).all()
    mastery_map = {kc: pm for kc, pm in mastery_rows if pm is not None}

    questions = [
        QuestionItem(
            question_id=item["kc_id"],
            kc_id=item["kc_id"],
            mastery=mastery_map.get(item["kc_id"], 0.5),
        )
        for item in raw
    ]
    interleaved = interleave_select(questions)

    return [
        {"kc_id": q.kc_id, "due": next(r["due"] for r in raw if r["kc_id"] == q.kc_id)}
        for q in interleaved.selected
    ]
