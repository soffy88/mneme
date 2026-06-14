"""E.1 — Daily mission service (assembly only)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omodul.daily_mission_workflow import DailyMissionConfig, DailyMissionInput, daily_mission_workflow
from services.models import DailyMission, KCMastery, MissionType, Streak


async def get_or_create_mission(db: AsyncSession, student_id: uuid.UUID, today: Optional[date] = None) -> dict:
    if today is None:
        today = datetime.now(timezone.utc).date()

    # 23:00 after → rest mission
    hour = datetime.now(timezone.utc).hour
    if hour >= 23:
        return {"mission_type": "rest", "content": {}, "streak": await _get_streak(db, student_id)}

    # Check existing
    existing = (await db.execute(
        select(DailyMission).where(DailyMission.student_id == student_id, DailyMission.date == today)
    )).scalar_one_or_none()
    if existing:
        return {"mission": _mission_dict(existing), "streak": await _get_streak(db, student_id)}

    # Gather kc_mastery state
    rows = (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id))).scalars().all()
    kc_mastery = {r.knowledge_point: round(r.p_mastery or 0.0, 4) for r in rows}
    now_dt = datetime.now(timezone.utc)
    last_seen = {
        r.knowledge_point: max(0, (now_dt - r.last_interaction_at).days)
        if r.last_interaction_at else 99
        for r in rows
    }
    available = [
        {"question_id": r.knowledge_point, "kc_id": r.knowledge_point, "difficulty": 0.5,
         "mastery": kc_mastery.get(r.knowledge_point, 0.5)}
        for r in rows
    ]

    config = DailyMissionConfig()
    inp = DailyMissionInput(
        user_id=str(student_id),
        mission_date=today.isoformat(),
        available_questions=available,
        kc_mastery=kc_mastery,
        last_seen_dates=last_seen,
    )
    result = daily_mission_workflow(config, inp, Path(f"/tmp/mneme/missions/{student_id}"))
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
    return {"mission": _mission_dict(mission), "streak": await _get_streak(db, student_id)}


async def complete_mission(db: AsyncSession, mission_id: uuid.UUID) -> dict:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(DailyMission)
        .where(DailyMission.id == mission_id)
        .values(completed=True, completed_at=now)
    )
    mission = (await db.execute(select(DailyMission).where(DailyMission.id == mission_id))).scalar_one_or_none()
    if not mission:
        return {"ok": False}

    streak = (await db.execute(select(Streak).where(Streak.student_id == mission.student_id))).scalar_one_or_none()
    today = now.date()
    if streak:
        if streak.last_completed_date == today:
            pass  # already counted
        elif streak.last_completed_date and (today - streak.last_completed_date).days == 1:
            new_streak = (streak.current_streak or 0) + 1
            await db.execute(
                update(Streak).where(Streak.student_id == mission.student_id)
                .values(current_streak=new_streak,
                        longest_streak=max(new_streak, streak.longest_streak or 0),
                        last_completed_date=today)
            )
        else:
            await db.execute(
                update(Streak).where(Streak.student_id == mission.student_id)
                .values(current_streak=1, last_completed_date=today)
            )
    else:
        db.add(Streak(student_id=mission.student_id, current_streak=1, longest_streak=1, last_completed_date=today))
    await db.flush()
    return {"ok": True}


async def _get_streak(db: AsyncSession, student_id: uuid.UUID) -> dict:
    streak = (await db.execute(select(Streak).where(Streak.student_id == student_id))).scalar_one_or_none()
    if not streak:
        return {"current_streak": 0, "longest_streak": 0}
    return {"current_streak": streak.current_streak or 0, "longest_streak": streak.longest_streak or 0}


def _mission_dict(m: DailyMission) -> dict:
    mt = m.mission_type
    mission_type_str = mt.value if hasattr(mt, "value") else str(mt) if mt else None
    return {
        "id": str(m.id),
        "date": m.date.isoformat() if m.date else None,
        "mission_type": mission_type_str,
        "content": m.content or {},
        "estimated_minutes": m.estimated_minutes,
        "completed": m.completed or False,
    }
