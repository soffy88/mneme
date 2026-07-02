"""
Cognitive service — Layer 4 装配层
接 process_interaction / mastery_overview / review_queue，
调 omodul/oskill/oprim，不写业务逻辑。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
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
from oprim.learning_metrics import (
    consecutive_active_days,
    weekly_digest_metrics,
    daily_report_text,
)
from oskill.interleave_select import QuestionItem, interleave_select

from services.models import (
    EffortfulGain,
    InteractionEvent,
    InteractionSource,
    KCMastery,
    MasterySnapshot,
    SocraticSession,
)

# 集中练习去抖阈值（小时）：见 process_interaction 内说明。
_MASSED_PRACTICE_DEBOUNCE_HOURS = 20.0


async def daily_report(db: AsyncSession, student_id: UUID, day=None) -> dict:
    """家长日报：把某天的学习活动汇成一句话（看成长非分数）。"""
    now = datetime.now(timezone.utc)
    d = day or now.date()
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows = (
        await db.execute(
            select(InteractionEvent.knowledge_point, InteractionEvent.is_correct)
            .where(InteractionEvent.student_id == student_id)
            .where(
                InteractionEvent.occurred_at >= start,
                InteractionEvent.occurred_at < end,
            )
            # fire_credit（M-H §4.8）是调度记账事件、非真实作答，不计学习量
            .where(InteractionEvent.source != InteractionSource.fire_credit)
        )
    ).all()
    n = len(rows)
    kcs = len({r[0] for r in rows})
    correct = sum(1 for r in rows if r[1])

    socratic = (
        await db.execute(
            select(func.count())
            .select_from(SocraticSession)
            .where(SocraticSession.student_id == student_id)
            .where(
                SocraticSession.created_at >= start, SocraticSession.created_at < end
            )
        )
    ).scalar() or 0

    weak = (
        await db.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.student_id == student_id)
            .where(KCMastery.p_mastery < 0.5)
        )
    ).scalar() or 0

    dig = await weekly_digest(db, student_id, now=now)
    streak = dig["current_streak"]

    text = daily_report_text(  # 成文在 oprim
        day_iso=d.isoformat(),
        n=n,
        distinct_kcs=kcs,
        correct=correct,
        socratic=int(socratic),
        streak=streak,
        weak_kc_count=int(weak),
    )

    return {
        "date": d.isoformat(),
        "report_text": text,
        "n_interactions": n,
        "distinct_kcs": kcs,
        "socratic": int(socratic),
        "current_streak": streak,
        "weak_kc_count": int(weak),
    }


async def weekly_digest(
    db: AsyncSession,
    student_id: UUID,
    now: Optional[datetime] = None,
) -> dict:
    """留存引擎：连续学习天数（任何练习都算）+ 本周成长摘要。
    streak 直接从 interaction_events 的活跃日算，反映真实活动而非"完成任务"。
    """
    now = now or datetime.now(timezone.utc)
    since60 = now - timedelta(days=60)
    rows = (
        await db.execute(
            select(
                InteractionEvent.occurred_at,
                InteractionEvent.knowledge_point,
                InteractionEvent.is_correct,
            )
            .where(InteractionEvent.student_id == student_id)
            .where(InteractionEvent.occurred_at >= since60)
            # fire_credit（M-H §4.8）是调度记账事件、非真实作答，不计学习量
            .where(InteractionEvent.source != InteractionSource.fire_credit)
        )
    ).all()

    today = now.date()
    active_dates = {r[0].date() for r in rows}
    streak = consecutive_active_days(active_dates, today)  # 算法在 oprim

    since7 = now - timedelta(days=7)
    recent = [r for r in rows if r[0] >= since7]
    days_active_7d = len({r[0].date() for r in recent})

    effort_7d = (
        await db.execute(
            select(func.count())
            .select_from(EffortfulGain)
            .where(EffortfulGain.student_id == student_id)
            .where(EffortfulGain.occurred_at >= since7)
        )
    ).scalar() or 0

    return weekly_digest_metrics(
        interactions_7d=recent,
        days_active_7d=days_active_7d,
        effort_gains_7d=int(effort_7d),
        streak=streak,
        active_today=(today in active_dates),
    )


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
    difficulty: Optional[float] = None,
    predicted_confidence: Optional[float] = None,
    predicted_r: Optional[float] = None,
    student_answer: Optional[str] = None,
    correct_answer: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """处理一次答题交互，落 kc_mastery + interaction_events + mastery_snapshots。"""
    now = now or datetime.now(timezone.utc)
    # Phase 2（IRT 通电）：未显式给难度时，按 kc_id 取 KU 难度；非 KU 知识点保持 None（行为不变）
    if difficulty is None:
        from services.models import KnowledgeUnit

        difficulty = (
            await db.execute(
                select(KnowledgeUnit.difficulty).where(KnowledgeUnit.id == kc_id)
            )
        ).scalar_one_or_none()
    # 努力收益（M-F）：记下更新前的 FSRS 稳定性，用于算 retention_delta
    old_card = (
        await db.execute(
            select(KCMastery.fsrs_card_json).where(
                KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id
            )
        )
    ).scalar_one_or_none()
    old_stability = float((old_card or {}).get("stability") or 0.0)

    store = PgStore(db)
    config = InteractionConfig()
    # 个性化 FSRS 调度：个体优先→群体→默认（无则用默认权重）。
    from services.fsrs_optimize_service import load_weights_for_student

    fsrs_params = await load_weights_for_student(db, student_id)
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
        difficulty=difficulty,
        predicted_confidence=predicted_confidence,
        predicted_r=predicted_r,
        # 集中练习去抖（学习科学：间隔重复≠集中练习）：距上次 FSRS 复习不足 20h 的
        # 重复作答只更新掌握度、不推进调度。真正的到期复习相隔数天，不受影响；
        # 同卷/同日连答不再把生题排到几天后导致"学了就忘"。
        min_review_interval_hours=_MASSED_PRACTICE_DEBOUNCE_HOURS,
        fsrs_parameters=fsrs_params,
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

    # 努力收益（M-F）：effortful_gain = struggle_score × retention_delta（FSRS 稳定性增量）
    #   仅在"吃力且确有记忆增益"时记录——对应"难但学得最牢"的信号
    new_card = (
        await db.execute(
            select(KCMastery.fsrs_card_json).where(
                KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id
            )
        )
    ).scalar_one_or_none()
    new_stability = float((new_card or {}).get("stability") or 0.0)
    retention_delta = max(0.0, new_stability - old_stability)
    struggle_score = min(max((time_spent_seconds or 0) / 120.0, 0.0), 1.0) * 0.7 + (
        0.3 if struggled else 0.0
    )
    if is_correct and struggle_score > 0.0 and retention_delta > 0.0:
        db.add(
            EffortfulGain(
                student_id=student_id,
                question_id=question_id,
                struggle_score=round(struggle_score, 4),
                retention_delta=round(retention_delta, 4),
                effortful_gain=round(struggle_score * retention_delta, 4),
            )
        )

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

    # 本学生各 KC 的识别维度 p_recognition（M-G，对抗惰性知识）
    recognition_map: dict[str, float] = {}
    if kc_ids:
        rec_rows = (
            await db.execute(
                select(KCMastery.knowledge_point, KCMastery.p_recognition)
                .where(KCMastery.student_id == student_id)
                .where(KCMastery.knowledge_point.in_(kc_ids))
                .where(KCMastery.p_recognition.is_not(None))
            )
        ).all()
        for kc, pr in rec_rows:
            recognition_map[kc] = pr

    result = []
    for item in items:
        kc = item["kc_id"]
        peer_vals = peer_data.get(kc, [item["effective_mastery"]])
        try:
            pct = compute_peer_percentile(item["effective_mastery"], peer_vals)
            item = {**item, "peer_percentile": pct.percentile}
        except (ValueError, ZeroDivisionError):
            item = {**item, "peer_percentile": None}
        item = {**item, "p_recognition": recognition_map.get(kc)}
        result.append(item)

    return result


async def weakness_roots(
    db: AsyncSession,
    student_id: UUID,
    *,
    mastery_threshold: float = 0.6,
    limit: int = 10,
) -> list[dict]:
    """前置图谱归因：对学生的薄弱知识点，沿 KU.prerequisites 上溯，找出
    同样薄弱/未练的前置——"你薄弱不在 X，而在前置 Y"。先补根、再补叶。
    """
    from services.models import KnowledgeUnit

    rows = (
        await db.execute(
            select(KCMastery.knowledge_point, KCMastery.p_mastery).where(
                KCMastery.student_id == student_id
            )
        )
    ).all()
    mastery: dict[str, float] = {kp: (pm if pm is not None else 0.0) for kp, pm in rows}
    weak_kps = [kp for kp, pm in mastery.items() if pm < mastery_threshold]
    if not weak_kps:
        return []

    weak_kus = (
        await db.execute(
            select(
                KnowledgeUnit.id, KnowledgeUnit.name, KnowledgeUnit.prerequisites
            ).where(KnowledgeUnit.id.in_(weak_kps))
        )
    ).all()

    prereq_ids = {p for _, _, prereqs in weak_kus for p in (prereqs or [])}
    prereq_names: dict[str, str] = {}
    if prereq_ids:
        prereq_names = {
            i: n
            for i, n in (
                await db.execute(
                    select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                        KnowledgeUnit.id.in_(prereq_ids)
                    )
                )
            ).all()
        }

    result: list[dict] = []
    for ku_id, name, prereqs in weak_kus:
        gaps = []
        for p in prereqs or []:
            pm = mastery.get(p)
            if pm is None:
                gaps.append(
                    {
                        "ku_id": p,
                        "name": prereq_names.get(p, p),
                        "p_mastery": None,
                        "status": "unpracticed",
                    }
                )
            elif pm < mastery_threshold:
                gaps.append(
                    {
                        "ku_id": p,
                        "name": prereq_names.get(p, p),
                        "p_mastery": round(pm, 4),
                        "status": "weak",
                    }
                )
        if gaps:
            result.append(
                {
                    "ku_id": ku_id,
                    "name": name,
                    "p_mastery": round(mastery.get(ku_id, 0.0), 4),
                    "weak_prerequisites": gaps,
                }
            )

    result.sort(key=lambda x: x["p_mastery"])
    return result[:limit]


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


async def _get_streak_dict(db: AsyncSession, student_id: UUID) -> dict:
    """Helper used by parent overview."""
    from services.models import Streak

    streak = (
        await db.execute(select(Streak).where(Streak.student_id == student_id))
    ).scalar_one_or_none()
    if not streak:
        return {"current_streak": 0, "longest_streak": 0}
    return {
        "current_streak": streak.current_streak or 0,
        "longest_streak": streak.longest_streak or 0,
    }
