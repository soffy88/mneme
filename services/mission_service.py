"""E.1 — Daily mission service (assembly only)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omodul.daily_mission_workflow import (
    DailyMissionConfig,
    DailyMissionInput,
    daily_mission_workflow,
)
from services.models import DailyMission, KCMastery, MissionType, Streak, WrongQuestion
from services.anon import anon_ref
from oskill.cold_start_single import cold_start_single, ColdStartInput
from obase.provider_registry import ProviderRegistry


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclass/pydantic instances to JSON-safe dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if hasattr(obj, "model_dump"):
        return {k: _to_jsonable(v) for k, v in obj.model_dump().items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(i) for i in obj]
    return obj


async def get_or_create_mission(
    db: AsyncSession,
    student_id: uuid.UUID,
    today: Optional[date] = None,
    _now: Optional[datetime] = None,
) -> dict:
    now = _now or datetime.now(timezone.utc)
    if today is None:
        today = now.date()

    # 23:00 after → rest mission
    if now.hour >= 23:
        return {
            "mission_type": "rest",
            "content": {},
            "streak": await _get_streak(db, student_id),
        }

    # Check existing
    existing = (
        await db.execute(
            select(DailyMission).where(
                DailyMission.student_id == student_id, DailyMission.date == today
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {
            "mission": _mission_dict(existing),
            "streak": await _get_streak(db, student_id),
        }

    # 冷启动检查
    wrong_count = (
        (
            await db.execute(
                select(WrongQuestion).where(WrongQuestion.student_id == student_id)
            )
        )
        .scalars()
        .all()
    )
    if not wrong_count:
        # 全新用户，走 cold_start_single
        caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None
        try:
            cs_res = await cold_start_single(
                ColdStartInput(
                    student_id=str(student_id),
                    input_type="text",
                    content="欢迎来到 Mneme，请完成以下入学诊断题以帮助我们了解你的水平。",
                ),
                caller=caller,
            )
            content = {
                "message": "新用户冷启动诊断",
                "diagnostics": _to_jsonable(cs_res),
            }
        except Exception as e:
            content = {"message": "冷启动初始化", "error": str(e)}

        mission = DailyMission(
            id=uuid.uuid4(),
            student_id=student_id,
            date=today,
            mission_type=MissionType.knowledge_focus,  # Cold start fallback type
            content=content,
            estimated_minutes=10,
        )
        db.add(mission)
        await db.flush()

        # Override mission type string for API response
        mission_res = _mission_dict(mission)
        mission_res["mission_type"] = "cold_start"
        return {"mission": mission_res, "streak": await _get_streak(db, student_id)}

    # Gather kc_mastery state
    rows = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )
    kc_mastery = {r.knowledge_point: round(r.p_mastery or 0.0, 4) for r in rows}
    now_dt = datetime.now(timezone.utc)
    last_seen = {
        r.knowledge_point: max(0, (now_dt - r.last_interaction_at).days)
        if r.last_interaction_at
        else 99
        for r in rows
    }
    available = [
        {
            "question_id": r.knowledge_point,
            "kc_id": r.knowledge_point,
            "difficulty": 0.5,
            "mastery": kc_mastery.get(r.knowledge_point, 0.5),
        }
        for r in rows
    ]

    config = DailyMissionConfig()
    inp = DailyMissionInput(
        user_id=anon_ref(student_id),
        mission_date=today.isoformat(),
        available_questions=available,
        kc_mastery=kc_mastery,
        last_seen_dates=last_seen,
    )
    result = daily_mission_workflow(
        config, inp, Path(f"/tmp/mneme/missions/{student_id}")
    )
    content = result.get("findings", {}) or {}

    mission = DailyMission(
        id=uuid.uuid4(),
        student_id=student_id,
        date=today,
        mission_type=MissionType.review if rows else MissionType.knowledge_focus,
        content=content,
        estimated_minutes=20,
    )
    db.add(mission)
    await db.flush()
    return {
        "mission": _mission_dict(mission),
        "streak": await _get_streak(db, student_id),
    }


async def complete_mission(db: AsyncSession, mission_id: uuid.UUID) -> dict:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(DailyMission)
        .where(DailyMission.id == mission_id)
        .values(completed=True, completed_at=now)
    )
    mission = (
        await db.execute(select(DailyMission).where(DailyMission.id == mission_id))
    ).scalar_one_or_none()
    if not mission:
        return {"ok": False}

    streak = (
        await db.execute(select(Streak).where(Streak.student_id == mission.student_id))
    ).scalar_one_or_none()
    today = now.date()
    _FREEZE_CAP = 3  # 护盾上限
    _FREEZE_EARN_EVERY = 7  # 每连胜 7 天赚 1 张护盾（绑持续检索习惯，非裸买）
    used_freeze = False
    if streak:
        gap = (
            (today - streak.last_completed_date).days
            if streak.last_completed_date
            else None
        )
        freezes = streak.freezes_available or 0
        if gap == 0:
            pass  # already counted today
        elif gap == 1:
            new_streak = (streak.current_streak or 0) + 1
            # 里程碑赚护盾：每 7 天连胜 +1（上限 3）
            if new_streak % _FREEZE_EARN_EVERY == 0:
                freezes = min(_FREEZE_CAP, freezes + 1)
            await db.execute(
                update(Streak)
                .where(Streak.student_id == mission.student_id)
                .values(
                    current_streak=new_streak,
                    longest_streak=max(new_streak, streak.longest_streak or 0),
                    last_completed_date=today,
                    freezes_available=freezes,
                )
            )
        elif gap == 2 and freezes > 0:
            # 缺一天但有护盾：消耗 1 张，连胜续上（不清零）
            new_streak = (streak.current_streak or 0) + 1
            used_freeze = True
            await db.execute(
                update(Streak)
                .where(Streak.student_id == mission.student_id)
                .values(
                    current_streak=new_streak,
                    longest_streak=max(new_streak, streak.longest_streak or 0),
                    last_completed_date=today,
                    freezes_available=freezes - 1,
                )
            )
        else:
            await db.execute(
                update(Streak)
                .where(Streak.student_id == mission.student_id)
                .values(current_streak=1, last_completed_date=today)
            )
    else:
        db.add(
            Streak(
                student_id=mission.student_id,
                current_streak=1,
                longest_streak=1,
                last_completed_date=today,
            )
        )
    await db.flush()
    return {"ok": True, "used_freeze": used_freeze}


async def _get_streak(db: AsyncSession, student_id: uuid.UUID) -> dict:
    streak = (
        await db.execute(select(Streak).where(Streak.student_id == student_id))
    ).scalar_one_or_none()
    if not streak:
        return {"current_streak": 0, "longest_streak": 0, "freezes_available": 2}
    return {
        "current_streak": streak.current_streak or 0,
        "longest_streak": streak.longest_streak or 0,
        "freezes_available": streak.freezes_available or 0,
    }


def _mission_dict(m: DailyMission) -> dict:
    mt = m.mission_type
    mission_type_str = mt.value if mt is not None else None
    return {
        "id": str(m.id),
        "date": m.date.isoformat() if m.date else None,
        "mission_type": mission_type_str,
        "content": m.content or {},
        "estimated_minutes": m.estimated_minutes,
        "completed": m.completed or False,
    }
