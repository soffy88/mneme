"""家长概览 / 导出 / 删除 / 预警（自 main 拆出）。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from obase.db import get_db
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.alert_service import get_student_alerts, run_alert_checks
from services.auth_deps import (
    get_current_user,
    require_student_access,
)
from services.models import (
    InteractionEvent,
    KCMastery,
    ParentStudent,
    SocraticSession,
    User,
    UserRole,
)

router = APIRouter(tags=["parent"])

# ===== §G.1 家长成长摘要 =====


@router.get("/v1/parent/overview/{student_id}")
async def get_parent_overview(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/overview/{student_id} — 学生学习摘要（家长视角）。"""
    rows = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )
    from services.learner_model import GATE

    weak_kc = [r for r in rows if (r.p_mastery or 0) < GATE]
    from services.cognitive_service import _get_streak_dict

    streak = await _get_streak_dict(db, student_id)
    recent_sessions = (
        (
            await db.execute(
                select(SocraticSession)
                .where(SocraticSession.student_id == student_id)
                .order_by(SocraticSession.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    from services.learner_model import MASTERED

    mastered = [r for r in rows if (r.p_mastery or 0) >= MASTERED]
    cur = streak.get("current_streak", 0) if isinstance(streak, dict) else 0
    # 进步优先(L6 第1律)：先讲掌握了什么/坚持了什么，问题项其后
    if mastered or cur:
        headline = (
            f"已掌握 {len(mastered)} 个知识点"
            + (f"、连续坚持 {cur} 天" if cur else "")
            + "，稳步在进步"
        )
    else:
        headline = "刚开始建立学习档案，做几道题就能看到进步"

    from oprim.learner_profile_summary import get_latest_learner_profile

    learner_profile = await get_latest_learner_profile(db, student_id)

    return {
        # 进步优先：headline + 掌握/坚持在前
        "headline": headline,
        "mastered_kc_count": len(mastered),
        "streak": streak,
        "total_kc_practiced": len(rows),
        # 需关注项在后（不是首屏主角）
        "weak_kc_count": len(weak_kc),
        "recent_sessions": len(recent_sessions),
        "learner_profile": learner_profile,
    }



# ===== §K.1 档案导出 =====


@router.get("/v1/parent/export/{student_id}")
async def get_export(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/export/{student_id} — 导出学生学习档案 JSON。"""
    user = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    mastery = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )
    events = (
        (
            await db.execute(
                select(InteractionEvent).where(
                    InteractionEvent.student_id == student_id
                )
            )
        )
        .scalars()
        .all()
    )
    archive = {
        "student_id": str(student_id),
        "name": user.name,
        "kc_mastery": [
            {"ku_id": r.knowledge_point, "p_mastery": round(r.p_mastery or 0, 4)}
            for r in mastery
        ],
        "interaction_count": len(events),
    }
    content = json.dumps(archive, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=archive_{student_id}.json"
        },
    )


# ===== §K.2 用户删除（合规） =====


@router.post("/v1/parent/delete-request/{student_id}")
async def post_delete_request(
    student_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/parent/delete-request/{student_id} — 软删除学生数据（合规红线）。
    鉴权：仅学生本人或其绑定家长可操作。"""
    if current_user.id != student_id:
        link = (
            await db.execute(
                select(ParentStudent).where(
                    ParentStudent.parent_id == current_user.id,
                    ParentStudent.student_id == student_id,
                )
            )
        ).scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=403, detail="无权删除该学生数据")
    user = (
        await db.execute(select(User).where(User.id == student_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Student not found")
    now = datetime.now(UTC)
    await db.execute(update(User).where(User.id == student_id).values(deleted_at=now))
    await db.commit()
    return {"ok": True, "deleted_at": now.isoformat(), "student_id": str(student_id)}


# ===== §G.2 家长预警 =====


def _ensure_parent_self(current_user: User, parent_id: UUID) -> None:
    """家长身份调用时 parent_id 必须是本人——防止绑定家长冒用他人 parent_id 读写预警。
    学生本人（已过 require_student_access，是预警的数据主体）放行。"""
    if current_user.role == UserRole.parent and current_user.id != parent_id:
        raise HTTPException(status_code=403, detail="parent_id 与当前用户不符")


@router.get("/v1/parent/alerts/{student_id}")
async def get_alerts(
    student_id: UUID,
    parent_id: UUID = Query(...),
    _auth: User = Depends(require_student_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/alerts/{student_id} — 家长预警列表。"""
    _ensure_parent_self(current_user, parent_id)
    return await get_student_alerts(db, student_id, parent_id)


@router.post("/v1/parent/alerts/{student_id}/check")
async def post_run_alert_checks(
    student_id: UUID,
    parent_id: UUID = Query(...),
    _auth: User = Depends(require_student_access),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/parent/alerts/{student_id}/check — 立即执行 5 类预警检查。"""
    _ensure_parent_self(current_user, parent_id)
    result = await run_alert_checks(db, student_id, parent_id)
    await db.commit()
    return {"checked": len(result), "alerts": result}


