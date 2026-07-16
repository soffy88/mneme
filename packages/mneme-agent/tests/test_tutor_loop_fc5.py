"""W2a FC-5 / V10 —— 独立 agent 进程零 mneme-DB 连接（pg_stat_activity 断言）。

FC-5 生效后（W2a 起有独立 agent 进程），V10 判定法从 W1 的 import/凭据审计换回
pg_stat_activity 连接监控。

harness（有 DB）：建 pilot → spawn agent subprocess（env 剥离 DB 凭据 + PGAPPNAME=
mneme-agent）→ **全程轮询 pg_stat_activity 断言无 application_name='mneme-agent' 的
backend 出现** → subprocess 经 HTTP 驱动 pilot 到 complete（returncode 0）→ 真人流量
确实经 HTTP 写入（is_correct）→ 清理 pilot。

双重铁证：subprocess 无 DATABASE_URL 却仍跑通（returncode 0）＝零 DB 依赖；
pg_stat_activity 全程无 mneme-agent backend ＝零 DB 连接。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid

import pytest

pytest.importorskip("oservi")
pytest.importorskip("mneme_core")

from sqlalchemy import text  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services.models import User, UserRole  # noqa: E402

API_BASE = "http://localhost:8000"
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_agent_runner.py")
KC_IDS = [
    "renjiao-math-g10-a-ku-二次函数的零点",
    "renjiao-math-g10-a-ku-三角函数的定义-单位圆",
    "renjiao-math-g10-a-ku004",
]
_STRIP = {
    "DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "REDIS_URL",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
}


async def _agent_backends() -> int:
    async with SessionLocal() as db:
        return (
            await db.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = :a"
                ),
                {"a": "mneme-agent"},
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_agent_process_zero_db_connection():
    sid = uuid.uuid4()
    async with SessionLocal() as db:  # harness 建 pilot
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.commit()
    try:
        env = {k: v for k, v in os.environ.items() if k not in _STRIP}
        env["PGAPPNAME"] = "mneme-agent"  # 若 agent 真连库，会以此 app_name 现形
        proc = subprocess.Popen(
            [sys.executable, RUNNER, str(sid), API_BASE, ",".join(KC_IDS)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        max_agent_backends = 0
        while proc.poll() is None:
            max_agent_backends = max(max_agent_backends, await _agent_backends())
            await asyncio.sleep(0.15)
        out, err = proc.communicate()
        max_agent_backends = max(max_agent_backends, await _agent_backends())

        assert proc.returncode == 0, (
            f"agent 未跑通（无 DB 凭据下）: rc={proc.returncode}\n{out}\n{err}"
        )
        assert max_agent_backends == 0, (
            f"V10 破：agent 进程出现 mneme-DB 连接 ×{max_agent_backends}"
        )

        # 真人流量确实经 HTTP 写入（不是 agent 直连 DB）
        async with SessionLocal() as db:
            corr = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM interaction_events WHERE student_id=:s AND is_correct"
                    ),
                    {"s": str(sid)},
                )
            ).scalar_one()
            assert corr >= 1, "P1: agent 经 HTTP 驱动应产生答对记录"
    finally:
        async with SessionLocal() as db:
            await db.execute(
                text("UPDATE users SET deleted_at=now()-interval '1 day' WHERE id=:i"),
                {"i": str(sid)},
            )
            await db.commit()
        async with SessionLocal() as db:
            from services.purge_service import purge_deleted_users

            await purge_deleted_users(db, grace_days=0)
            await db.commit()
