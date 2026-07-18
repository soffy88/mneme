"""tasks.memory_tasks —— C5（W2C）working-memory TTL 清理定时任务。

任务函数自建独立 engine 并内部 ``asyncio.run()``（同 purge_tasks.py 惯例）——不能在
pytest-asyncio 已有的事件循环里调用，故本测试**不用** ``@pytest.mark.asyncio``，
用普通同步测试 + 独立 ``asyncio.run()`` 做设置/验证（对照 Celery worker 的真实调用
方式：全新进程/线程，任务调用时不存在外层事件循环）。

真提交（不是 rollback 惯例）——测试本身就是验证"过期行真的被删除"。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from obase.db import SessionLocal
from tasks.memory_tasks import cleanup_expired_working_memory_task


def test_cleanup_task_deletes_expired_working_memory_via_own_engine():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async def _insert_expired():
        async with SessionLocal() as db:
            await db.execute(
                text(
                    "INSERT INTO agent.working_memory "
                    "(student_id, session_id, content, expires_at) "
                    "VALUES (CAST(:sid AS uuid), 's1', CAST(:c AS jsonb), :expires)"
                ),
                {
                    "sid": str(sid),
                    "c": json.dumps({"note": "expired"}),
                    "expires": now - timedelta(minutes=1),
                },
            )
            await db.commit()

    async def _count_remaining() -> int:
        async with SessionLocal() as db:
            return (
                await db.execute(
                    text(
                        "SELECT count(*) FROM agent.working_memory "
                        "WHERE student_id = CAST(:sid AS uuid)"
                    ),
                    {"sid": str(sid)},
                )
            ).scalar_one()

    asyncio.run(_insert_expired())

    result = cleanup_expired_working_memory_task()
    assert result["deleted_count"] >= 1

    assert asyncio.run(_count_remaining()) == 0
