"""daily_plan_prefs_service.py — V.2 每日计划参数可见+可配置

同 accessibility_service.py 的 get/set 三件套模式：偏好存 users.daily_plan_prefs
（JSONB，白名单字段，部分更新）。GATE（掌握度阈值）不在此列——它是
services/learner_model.py 的单源常量，BKT薄弱判定/前置锁定/小测选题/词汇FSRS
都读同一个值，做成 per-student 会让同一知识点在不同入口"薄弱"判定不一致，
破坏既有反漂移红线，明确不开放。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import User

_DEFAULT_PREFS = {
    "budget_minutes": None,  # 每日学习时长预算(分钟)，None=不限
    "late_night_hour": 22,
    "late_night_minute": 30,
    "weak_max_items": 3,
    "new_max_items": 2,
}
_ALLOWED_KEYS = set(_DEFAULT_PREFS.keys())


async def get_daily_plan_prefs(db: AsyncSession, student_id: uuid.UUID) -> dict:
    row = (
        await db.execute(select(User.daily_plan_prefs).where(User.id == student_id))
    ).scalar_one_or_none()
    return {**_DEFAULT_PREFS, **(row or {})}


def _validate(updates: dict) -> str | None:
    """返回错误信息，None 表示通过。数值越界会让 daily_plan_service 算出负数/离谱
    结果，值得在这里挡住，而不是让脏值悄悄流进调度算法。"""
    if "budget_minutes" in updates:
        v = updates["budget_minutes"]
        if v is not None and (not isinstance(v, int) or v <= 0):
            return "budget_minutes 必须是正整数或 null(不限)"
    if "late_night_hour" in updates:
        v = updates["late_night_hour"]
        if not isinstance(v, int) or not (0 <= v <= 23):
            return "late_night_hour 必须是 0-23 的整数"
    if "late_night_minute" in updates:
        v = updates["late_night_minute"]
        if not isinstance(v, int) or not (0 <= v <= 59):
            return "late_night_minute 必须是 0-59 的整数"
    for key in ("weak_max_items", "new_max_items"):
        if key in updates:
            v = updates[key]
            if not isinstance(v, int) or v < 0:
                return f"{key} 必须是 >=0 的整数"
    return None


async def set_daily_plan_prefs(
    db: AsyncSession, student_id: uuid.UUID, updates: dict
) -> dict:
    """合并写入（部分更新，未传的字段保留原值）；未知字段拒绝，避免偏好字段无序膨胀。"""
    unknown = set(updates) - _ALLOWED_KEYS
    if unknown:
        return {"error": f"未知偏好字段: {sorted(unknown)}"}

    err = _validate(updates)
    if err:
        return {"error": err}

    current = await get_daily_plan_prefs(db, student_id)
    merged = {**current, **updates}
    await db.execute(
        update(User).where(User.id == student_id).values(daily_plan_prefs=merged)
    )
    await db.commit()
    return merged
