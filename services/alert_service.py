"""G.2 — Parent alert evaluators (5 types, assembly only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import (
    AlertLevel,
    AlertType,
    DailyMission,
    InteractionEvent,
    ParentAlert,
    SocraticSession,
    KCMastery,
)


async def get_student_alerts(
    db: AsyncSession, student_id: uuid.UUID, parent_id: uuid.UUID
) -> list[dict]:
    """Read unread parent_alerts for a student."""
    rows = (
        (
            await db.execute(
                select(ParentAlert)
                .where(
                    ParentAlert.student_id == student_id,
                    ParentAlert.parent_id == parent_id,
                )
                .order_by(ParentAlert.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "type": r.alert_type.value if r.alert_type else None,
            "level": r.alert_level.value if r.alert_level else None,
            "content": r.content,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def run_alert_checks(
    db: AsyncSession, student_id: uuid.UUID, parent_id: uuid.UUID
) -> list[dict]:
    """Run all 5 alert evaluators. Layer 4 only — reads DB, no business logic."""
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    # 1. emotion: recent socratic sessions with high session count
    sessions = (
        (
            await db.execute(
                select(SocraticSession).where(
                    SocraticSession.student_id == student_id,
                    SocraticSession.created_at >= now - timedelta(days=3),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(sessions) >= 5:
        alerts.append(
            {
                "type": AlertType.emotion,
                "level": AlertLevel.attention,
                "content": f"3天内苏格拉底会话 {len(sessions)} 次，可能遇到困难",
            }
        )

    # 2. task_missing: consecutive incomplete missions
    missions = (
        (
            await db.execute(
                select(DailyMission)
                .where(
                    DailyMission.student_id == student_id,
                    DailyMission.date >= (now - timedelta(days=5)).date(),
                )
                .order_by(DailyMission.date.desc())
            )
        )
        .scalars()
        .all()
    )
    consecutive_miss = sum(1 for m in missions if not m.completed)
    if consecutive_miss >= 3:
        alerts.append(
            {
                "type": AlertType.task_missing,
                "level": AlertLevel.important,
                "content": f"连续 {consecutive_miss} 天未完成任务",
            }
        )

    # 3. time_drop: interaction count this week vs last week
    this_week = (
        await db.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at >= now - timedelta(days=7),
            )
        )
    ).scalar() or 0
    last_week = (
        await db.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at.between(
                    now - timedelta(days=14), now - timedelta(days=7)
                ),
            )
        )
    ).scalar() or 0
    if last_week > 0 and this_week < last_week * 0.5:
        alerts.append(
            {
                "type": AlertType.time_drop,
                "level": AlertLevel.attention,
                "content": f"本周学习时长大幅下降 ({this_week} vs 上周 {last_week} 次)",
            }
        )

    # 4. late_night: interactions after 23:00
    late = (
        await db.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at >= now - timedelta(days=3),
                func.extract("hour", InteractionEvent.occurred_at) >= 23,
            )
        )
    ).scalar() or 0
    if late >= 2:
        alerts.append(
            {
                "type": AlertType.late_night,
                "level": AlertLevel.notice,
                "content": f"近3天有 {late} 次深夜（23点后）答题记录",
            }
        )

    # 5. score_drop: KCs with consistent negative trend
    mastery_rows = (
        (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id, KCMastery.p_mastery <= 0.3
                )
            )
        )
        .scalars()
        .all()
    )
    if len(mastery_rows) >= 3:
        alerts.append(
            {
                "type": AlertType.score_drop,
                "level": AlertLevel.attention,
                "content": f"{len(mastery_rows)} 个知识点掌握度低于30%",
            }
        )

    # Write alerts to DB and return（按 (parent,student,type,当日) 去重——定时任务每天跑，同一预警一天只落一条）
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    existing_types = set(
        (
            await db.execute(
                select(ParentAlert.alert_type).where(
                    ParentAlert.parent_id == parent_id,
                    ParentAlert.student_id == student_id,
                    ParentAlert.created_at >= day_start,
                )
            )
        )
        .scalars()
        .all()
    )
    alerts = [a for a in alerts if a["type"] not in existing_types]
    written = []
    for a in alerts:
        pa = ParentAlert(
            id=uuid.uuid4(),
            parent_id=parent_id,
            student_id=student_id,
            alert_type=a["type"],
            alert_level=a["level"],
            content=a["content"],
        )
        db.add(pa)
        written.append(
            {
                "type": a["type"].value,
                "level": a["level"].value,
                "content": a["content"],
            }
        )
    if alerts:
        await db.flush()
    return written
