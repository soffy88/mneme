"""oskill.partner_dispatch — W5 A3 Partner 心跳算法：组合 evaluator + 文案生成 +
节流/去重，产出"可以推送"的候选列表。

组合 ≥2 个不同 oprim（check_partner_review_due + generate_partner_push_text），
中间的去重过滤是本 oskill 自己的算法逻辑（同 DeepTutor AlerterEngine 的
throttle_seconds/dedup_bucket_seconds 语义：一天最多一条同类型提醒，避免轰炸——
同 tasks/partner_tasks.py 既有"一天最多一条提醒"规则），不引入 oservi 依赖
（oservi 目前只是本机 dev 挂载，非正式生产依赖，见 W5 决策）。

本函数只做计算，不发送、不写库——发送与记录推送流水是 tasks/partner_heartbeat.py
（服务/任务层）的职责，保持 3O→services 单向依赖不倒挂。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from oprim.check_partner_review_due import check_review_due
from oprim.generate_partner_push_text import generate_push_text


async def _already_sent_today(
    db: AsyncSession, *, student_id: Any, channel: str, dedup_key: str
) -> bool:
    row = (
        await db.execute(
            sa_text(
                "SELECT 1 FROM agent.partner_push_log "
                "WHERE student_id = :sid AND channel = :ch AND dedup_key = :dk "
                "LIMIT 1"
            ),
            {"sid": student_id, "ch": channel, "dk": dedup_key},
        )
    ).scalar_one_or_none()
    return row is not None


async def compute_partner_pushes(
    db: AsyncSession,
    *,
    llm_caller: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
) -> list[dict[str, Any]]:
    """返回本次心跳该真实发出的推送列表：
    [{student_id, channel, target, text, dedup_key, event_type}, ...]

    已在今天推送过同 (student_id, channel, dedup_key) 的候选会被过滤掉——
    去重窗口固定为"天"，同 partner_tasks.py 既有节流粒度。
    """
    from services.models import User

    candidates = await check_review_due(db)
    if not candidates:
        return []

    today_key_suffix = datetime.now(timezone.utc).date().isoformat()
    ready: list[dict[str, Any]] = []

    for event in candidates:
        dedup_key = f"{event['event_type']}:{today_key_suffix}"
        if await _already_sent_today(
            db,
            student_id=event["student_id"],
            channel=event["channel"],
            dedup_key=dedup_key,
        ):
            continue

        student = await db.get(User, event["student_id"])
        name = (student.name if student else None) or "同学"

        text = await generate_push_text(
            name=name, due_count=event["due_count"], llm_caller=llm_caller
        )

        ready.append(
            {
                "student_id": event["student_id"],
                "channel": event["channel"],
                "target": event["target"],
                "text": text,
                "dedup_key": dedup_key,
                "event_type": event["event_type"],
            }
        )

    return ready
