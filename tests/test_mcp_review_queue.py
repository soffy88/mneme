"""A2 — GetReviewQueue 工具：只返回到期项，按 (priority, due_at) 升序（error-linked 先出）。

单 session 不 commit，退出回滚。需 mneme_core（②-0 打包）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

pytest.importorskip("mneme_core")

from obase.db import SessionLocal  # noqa: E402
from services.mcp_router import tool_get_review_queue  # noqa: E402
from services.models import (  # noqa: E402
    InteractionEvent,
    InteractionSource,
    KCMastery,
    User,
    UserRole,
)

ERR_KC = "renjiao-math-g10-a-ku-二次函数的零点"  # error-linked → priority=1
SCHED_KC = "renjiao-math-g10-a-ku-三角函数的定义-单位圆"  # 无错误 → priority=2
FUTURE_KC = "renjiao-math-g10-a-ku004"  # 未到期 → 应被过滤

PAST = "2020-01-01T00:00:00+00:00"
FUTURE = "2999-01-01T00:00:00+00:00"


def _mastery(sid, kc, due):
    return KCMastery(
        student_id=sid,
        knowledge_point=kc,
        p_mastery=0.5,
        p_init=0.3,
        p_transit=0.3,
        p_guess=0.2,
        p_slip=0.1,
        fsrs_card_json={"due": due},
    )


@pytest.mark.asyncio
async def test_review_queue_due_filter_and_priority_sort():
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()
        db.add(_mastery(sid, ERR_KC, PAST))
        db.add(_mastery(sid, SCHED_KC, PAST))
        db.add(_mastery(sid, FUTURE_KC, FUTURE))
        db.add(
            InteractionEvent(
                student_id=sid,
                knowledge_point=ERR_KC,
                source=InteractionSource.paper,
                is_correct=False,
            )
        )
        await db.flush()

        now = datetime.now(timezone.utc).timestamp()
        res = await tool_get_review_queue(
            db, sid, [ERR_KC, SCHED_KC, FUTURE_KC], now=now
        )
        q = res["review_queue"]
        ids = [r["kc_id"] for r in q]

        assert FUTURE_KC not in ids  # 未到期被过滤
        assert ids == [ERR_KC, SCHED_KC]  # error-linked(priority=1) 先出
        assert q[0]["priority"] == 1
        assert q[1]["priority"] == 2
