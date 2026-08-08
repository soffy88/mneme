"""每日任务 / 学科计划 / 计划偏好（自 main 拆出）。"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.daily_plan_prefs_service import (
    get_daily_plan_prefs,
    set_daily_plan_prefs,
)
from services.daily_plan_service import build_daily_plan
from services.mission_service import complete_mission, get_or_create_mission
from services.models import DailyMission, User

router = APIRouter(tags=["plan"])

# ===== §E.1 今日目标 =====


@router.get("/v1/missions/today/{student_id}")
async def get_today_mission(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/missions/today/{student_id} — 获取或创建今日目标。"""
    try:
        result = await get_or_create_mission(db, student_id)
        await db.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v1/missions/{mission_id}/complete")
async def post_complete_mission(
    mission_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/missions/{id}/complete — 完成任务，更新 streak。仅任务归属学生本人。"""
    mission = await db.get(DailyMission, mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    _ensure_student_self(current_user, mission.student_id)
    result = await complete_mission(db, mission_id)
    await db.commit()
    return result


# ===== §E.2 每日学科计划（桩接口） =====


@router.get("/v1/daily-plan/{student_id}")
async def get_daily_plan(
    student_id: UUID,
    subject: str | None = Query(None),
    budget_minutes: int | None = Query(
        None, description="U.20 会话预算：不传则不裁剪（保持既有行为）"
    ),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/daily-plan/{student_id}?subject=xxx&budget_minutes=25 — 每日学习计划规则引擎。
    鉴权：学生本人或绑定家长（原先只验登录不验归属）。

    subject 不传 → 所有科目汇总（首页用）
    subject=math  → 单科详细（学科页用）
    budget_minutes 不传 → 不裁剪（默认，避免悄悄改变现有前端响应）；
    传入则按 20-30 分钟量级的会话预算贪心裁剪任务列表（U.20 L5 会话时间设计）。

    优先级：P1 FSRS到期 > P2 错题 > P3 薄弱 > P4 新知识点
    """
    from services.daily_plan_service import build_daily_plan

    return await build_daily_plan(
        db, student_id, subject=subject, budget_minutes=budget_minutes
    )



# ===== §V.2 每日计划参数可见+可配置 =====

from services.daily_plan_prefs_service import (
    get_daily_plan_prefs,
    set_daily_plan_prefs,
)


class DailyPlanPrefsReq(BaseModel):
    budget_minutes: int | None = None
    late_night_hour: int | None = None
    late_night_minute: int | None = None
    weak_max_items: int | None = None
    new_max_items: int | None = None


@router.get("/v1/users/{student_id}/daily-plan-prefs")
async def get_user_daily_plan_prefs(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/users/{student_id}/daily-plan-prefs — 每日计划生成参数（时长预算/
    晚间截止/薄弱与新学每日条数上限），跨设备持久化。GATE 掌握度阈值不在此列
    （单源常量，见 services/learner_model.py）。"""
    return await get_daily_plan_prefs(db, student_id)


# ===== 康奈尔笔记进度云同步（Phase C；自报进度 ≠ BKT） =====

# cornell 路由已迁至 services/routers/cornell.py


@router.post("/v1/users/{student_id}/daily-plan-prefs")
async def post_user_daily_plan_prefs(
    student_id: UUID,
    body: DailyPlanPrefsReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/users/{student_id}/daily-plan-prefs — 更新每日计划参数（部分更新）。
    仅本人。用 exclude_unset 区分"字段未传"与"显式传 null"——budget_minutes 的合法值
    本身包含 null(=不限)，不能用"非 None 才更新"的简单过滤（会导致永远清不回不限）。
    """
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能设置本人偏好")
    updates = body.model_dump(exclude_unset=True)
    result = await set_daily_plan_prefs(db, student_id, updates)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


