"""成就 / 联赛 / 学习者模型 / 用户设置 / 情感 / 纵向模式（自 main 拆出）。"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.accessibility_service import (
    get_accessibility_prefs,
    read_aloud_ku,
    set_accessibility_prefs,
)
from services.auth_deps import (
    get_current_user,
    require_student_access,
)
from services.feature_flags import (
    PEDAGOGY_AFFECT,
    PEDAGOGY_LEAGUE,
    PEDAGOGY_OLM,
    pedagogy_enabled,
)
from services.learner_model import MASTERED as _MASTERED
from services.models import (
    EffortfulGain,
    InteractionEvent,
    KCMastery,
    User,
    UserRole,
)

router = APIRouter(tags=["progress"])

@router.get("/v1/achievements/{student_id}")
async def get_achievements(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """学生成就/徽章（从真实数据算）——驱动"愿意用"的动机钩子。多档位，含下一档进度。"""
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(InteractionEvent.occurred_at).where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at >= now - timedelta(days=120),
            )
        )
    ).all()
    active = {r[0].date() for r in rows}
    cur, streak = (
        (now.date() if now.date() in active else now.date() - timedelta(days=1)),
        0,
    )
    while cur in active:
        streak += 1
        cur -= timedelta(days=1)
    total_correct = (
        await db.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.is_correct.is_(True),
            )
        )
    ).scalar() or 0
    mastered = (
        await db.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.student_id == student_id, KCMastery.p_mastery >= _MASTERED)
        )
    ).scalar() or 0
    effort = (
        await db.execute(
            select(func.count())
            .select_from(EffortfulGain)
            .where(EffortfulGain.student_id == student_id)
        )
    ).scalar() or 0

    defs = [
        ("streak", "🔥", "坚持不懈", [3, 7, 30], "天连续", streak),
        ("correct", "✅", "做题能手", [10, 50, 200], "题做对", int(total_correct)),
        ("mastered", "⭐", "融会贯通", [5, 20, 50], "个知识点掌握", int(mastered)),
        ("effort", "💪", "真努力", [5, 20, 60], "次有效努力", int(effort)),
    ]
    out = []
    for aid, icon, name, tiers, unit, val in defs:
        level = sum(1 for t in tiers if val >= t)
        out.append(
            {
                "id": aid,
                "icon": icon,
                "name": name,
                "unit": unit,
                "value": val,
                "level": level,
                "max_level": len(tiers),
                "next_target": tiers[level] if level < len(tiers) else None,
            }
        )
    return {"achievements": out}


def _league_tier(pct: float) -> str:
    """百分位 → 匿名段位（SDT 归属，无 PII）。"""
    if pct >= 90:
        return "钻石"
    if pct >= 70:
        return "黄金"
    if pct >= 40:
        return "白银"
    return "青铜"


@router.get("/v1/league/{student_id}")
async def get_league(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """匿名同年级联赛（SDT 归属）：仅返回本人在同年级中的百分位/段位/队列人数，
    不含任何他人身份或分数（合规：未成年不暴露真实排名/PII）。
    U.24 教学机制 feature-flag（PEDAGOGY_LEAGUE_ENABLED=0 急停）。"""

    if not pedagogy_enabled(PEDAGOGY_LEAGUE):
        raise HTTPException(status_code=404, detail="Feature disabled")
    from oprim import compute_peer_percentile

    grade = (
        await db.execute(select(User.grade).where(User.id == student_id))
    ).scalar_one_or_none()

    # 同年级学生的"已掌握 KU 数"作为联赛指标（努力/掌握代理，非绝对分数）
    counts_stmt = (
        select(KCMastery.student_id, func.count().label("n"))
        .join(User, User.id == KCMastery.student_id)
        .where(
            User.role == UserRole.student,
            User.deleted_at.is_(None),
            KCMastery.p_mastery >= _MASTERED,
        )
    )
    if grade:
        counts_stmt = counts_stmt.where(User.grade == grade)
    counts_stmt = counts_stmt.group_by(KCMastery.student_id)
    rows = (await db.execute(counts_stmt)).all()

    peer_values = [float(n) for _, n in rows]
    my_value = float(next((n for sid, n in rows if sid == student_id), 0))
    # 队列里没有别人（或本人无掌握）时给中位，避免误导
    if len(peer_values) < 2:
        return {
            "grade": grade,
            "cohort_size": len(peer_values),
            "my_mastered": int(my_value),
            "percentile": None,
            "tier": None,
            "note": "同年级样本不足，暂无排名",
        }
    res = compute_peer_percentile(my_value, peer_values)
    pct = round(float(res.percentile), 1)
    return {
        "grade": grade,
        "cohort_size": len(peer_values),
        "my_mastered": int(my_value),
        "percentile": pct,
        "tier": _league_tier(pct),
    }


@router.get("/v1/learner-model/{student_id}/{ku_id}")
async def get_learner_model(
    student_id: UUID,
    ku_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """开放学习者模型(OLM，教育理念 03)：把 KT 模型**透明摊给学生自己看**以促元认知。
    返回长期掌握 P(L)、此刻可提取性 R、有效掌握、错因画像(粗心 vs 没学会)、下次复习。
    "协商挑战"（我觉得我会了→做一题验证）复用现有 practice/submit，本端点只做透明读。
    U.24 教学机制 feature-flag（PEDAGOGY_OLM_ENABLED=0 急停）。"""

    if not pedagogy_enabled(PEDAGOGY_OLM):
        raise HTTPException(status_code=404, detail="Feature disabled")
    from oprim import KCState
    from oprim._cognitive import bkt_error_weights
    from oprim.fsrs_engine import fsrs_retrievability

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == ku_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"ku_id": ku_id, "started": False}

    pm = row.p_mastery or 0.0
    card = row.fsrs_card_json
    r_val = fsrs_retrievability(card_dict=card) if card else None
    effective = round(pm * r_val, 4) if r_val is not None else round(pm, 4)

    state = KCState(
        kc_id=ku_id,
        p_init=row.p_init,
        p_transit=row.p_transit,
        p_guess=row.p_guess,
        p_slip=row.p_slip,
        p_mastery=pm,
        p_recognition=row.p_recognition,
        p_recognition_init=row.p_recognition_init,
        long_term_mastery=row.long_term_mastery,
        last_interaction_ts=row.last_interaction_at,
        n_attempts=row.n_attempts or 0,
    )
    careless_w, dontknow_w = bkt_error_weights(state=state)
    tot = (careless_w + dontknow_w) or 1.0

    return {
        "ku_id": ku_id,
        "started": True,
        "p_mastery": round(pm, 4),  # 长期 P(L)
        "retrievability": round(r_val, 4)
        if r_val is not None
        else None,  # 此刻可提取性
        "effective_mastery": effective,  # P(L)×R
        "recognition": round(row.p_recognition, 4) if row.p_recognition else None,
        # 错因画像：粗心(会但错) vs 没学会
        "error_profile": {
            "careless": round(careless_w / tot, 3),
            "dontknow": round(dontknow_w / tot, 3),
        },
        "attempts": row.n_attempts or 0,
        "next_review": card.get("due") if card else None,
        "last_interaction": row.last_interaction_at.isoformat()
        if row.last_interaction_at
        else None,
    }


class ExamDateReq(BaseModel):
    exam_date: date | None = None  # None 清除


@router.post("/v1/users/{student_id}/exam-date")
async def set_exam_date(
    student_id: UUID,
    body: ExamDateReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """设置本人考试日期（教育理念 06 考期感知）。临考(≤14天)日计划停推新知、向巩固倾斜。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人考试日期")
    await db.execute(
        update(User).where(User.id == student_id).values(exam_date=body.exam_date)
    )
    await db.commit()
    countdown = (body.exam_date - date.today()).days if body.exam_date else None
    return {
        "exam_date": body.exam_date.isoformat() if body.exam_date else None,
        "exam_countdown_days": countdown,
    }


class PrivacyReq(BaseModel):
    share_process_with_parent: bool


@router.post("/v1/users/{student_id}/privacy")
async def set_privacy(
    student_id: UUID,
    body: PrivacyReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """L6 隐私分层：学生本人协商是否向家长开放过程数据(错题详情/情绪/求助)。结果数据不受此限。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人隐私")
    await db.execute(
        update(User)
        .where(User.id == student_id)
        .values(share_process_with_parent=body.share_process_with_parent)
    )
    await db.commit()
    return {"share_process_with_parent": body.share_process_with_parent}


# ===== §U.23 UDL 无障碍 =====



class AccessibilityPrefsReq(BaseModel):
    font_size: str | None = None
    line_height: str | None = None
    color_scheme: str | None = None
    low_bandwidth: bool | None = None


@router.get("/v1/users/{student_id}/accessibility")
async def get_user_accessibility(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/users/{student_id}/accessibility — 无障碍偏好（字体/行距/配色/低带宽），
    跨设备持久化；渲染在 mneme-web 前端，这里只存偏好。"""
    return await get_accessibility_prefs(db, student_id)


@router.post("/v1/users/{student_id}/accessibility")
async def post_user_accessibility(
    student_id: UUID,
    body: AccessibilityPrefsReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/users/{student_id}/accessibility — 更新无障碍偏好（部分更新）。仅本人。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人偏好")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    result = await set_accessibility_prefs(db, student_id, updates)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result



@router.post("/v1/knowledge-points/{ku_id}/read-aloud")
async def post_ku_read_aloud(
    ku_id: str,
    language: str = Query("zh"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/knowledge-points/{ku_id}/read-aloud — 公式/知识点内容朗读（UDL）。
    展平 rich_content 为可读文本后调 TTS；无内容时 available=False，不报错。"""
    result = await read_aloud_ku(db, ku_id, language=language)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    return result


@router.get("/v1/affect/{student_id}")
async def get_affect(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """情感感知（教育理念 08）：从近 12 次作答的**行为信号**估计情感态(挫败/脱离/心流/中性)
    + 自适应建议。启发式，无生物特征采集。
    U.24 教学机制 feature-flag（PEDAGOGY_AFFECT_ENABLED=0 急停）。"""

    if not pedagogy_enabled(PEDAGOGY_AFFECT):
        raise HTTPException(status_code=404, detail="Feature disabled")
    from oprim.affect import affect_estimate

    rows = (
        await db.execute(
            select(
                InteractionEvent.is_correct,
                InteractionEvent.time_spent_seconds,
            )
            .where(InteractionEvent.student_id == student_id)
            .order_by(InteractionEvent.occurred_at.desc())
            .limit(12)
        )
    ).all()
    if not rows:
        return {"state": "neutral", "adaptation": "keep", "n": 0}

    # 最近在前：算尾部连错/连对、快速做对（用可得的 is_correct/time_spent 行为信号）
    consecutive_wrong = 0
    for is_c, _t in rows:
        if is_c is False:
            consecutive_wrong += 1
        else:
            break
    correct_streak = 0
    for is_c, _t in rows:
        if is_c is True:
            correct_streak += 1
        else:
            break
    # 快速放弃代理：做错且用时极短（<8s）视为 give-up
    give_ups = [1 for c, t in rows if c is False and t is not None and t < 8]
    give_up_rate = len(give_ups) / len(rows)
    fast_times = [t for c, t in rows if c is True and t is not None]
    fast_correct = bool(fast_times) and (sum(fast_times) / len(fast_times)) < 30.0

    est = affect_estimate(
        consecutive_wrong=consecutive_wrong,
        give_up_rate=give_up_rate,
        recent_correct_streak=correct_streak,
        fast_correct=fast_correct,
    )
    return {**est, "n": len(rows)}



# ===== §J.1 纵向分析 =====


@router.get("/v1/patterns/{student_id}")
async def get_patterns(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/patterns/{student_id} — 个人学习模式分析。"""
    from oskill.longitudinal_pattern import AttemptRecord, longitudinal_pattern

    events = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == student_id)
                .order_by(InteractionEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    records = [
        AttemptRecord(
            question_id=str(e.question_id) if e.question_id else e.knowledge_point,
            kc_id=e.knowledge_point,
            correct=e.is_correct,
            timestamp=e.occurred_at.timestamp() if e.occurred_at else 0.0,
        )
        for e in events
    ]
    if not records:
        return {"patterns": [], "student_id": str(student_id)}
    result = longitudinal_pattern(records)
    return {
        "student_id": str(student_id),
        "improving_kcs": result.improving_kcs,
        "forgetting_kcs": result.forgetting_kcs,
        "plateau_kcs": result.plateau_kcs,
        "overall_trend": round(result.overall_trend, 4),
        "patterns": [
            {
                "ku_id": t.kc_id,
                "trend": round(t.trend, 4),
                "current_accuracy": round(t.current_accuracy, 4),
                "is_forgetting": t.is_forgetting,
                "is_plateau": t.is_plateau,
            }
            for t in result.kc_trajectories.values()
        ],
    }


