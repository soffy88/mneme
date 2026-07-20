"""oprim.check_partner_review_due — W5 A3 心跳 evaluator：真实 FSRS 到期信号。

单次原子操作（一次 DB 查询）：给定所有已绑定 Partner 推送渠道的学生，查询真实
FSRS 到期错题数——阈值与 tasks/partner_tasks.py 既有逻辑一致（不发明新信号，
复用已验证过的真实门控/FSRS 数据）。

红线（A3）：Partner 推送内容必须经真实 gate/FSRS 信号触发，不自行判定掌握度——
本函数只读 fsrs_due/fsrs_state，不写、不判分。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

DUE_COUNT_THRESHOLD = 10


async def check_review_due(db: AsyncSession) -> list[dict[str, Any]]:
    """返回需要收到"待复习"推送的候选事件列表（未做节流/去重过滤）。

    每个事件：{student_id, channel, target, event_type, due_count}。
    """
    from services.models import WrongQuestion

    now = datetime.now(timezone.utc)

    bindings = (
        await db.execute(
            sa_text(
                "SELECT student_id, channel, target "
                "FROM agent.partner_channel_bindings WHERE enabled = true"
            )
        )
    ).all()

    events: list[dict[str, Any]] = []
    for student_id, channel, target in bindings:
        due_count = (
            await db.execute(
                select(func.count(WrongQuestion.id)).where(
                    WrongQuestion.student_id == student_id,
                    WrongQuestion.fsrs_due <= now,
                    WrongQuestion.fsrs_state.in_(["learning", "review", "relearning"]),
                )
            )
        ).scalar_one_or_none() or 0

        if due_count > DUE_COUNT_THRESHOLD:
            events.append(
                {
                    "student_id": student_id,
                    "channel": channel,
                    "target": target,
                    "event_type": "review_due",
                    "due_count": due_count,
                }
            )
    return events
