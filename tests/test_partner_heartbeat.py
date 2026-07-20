"""W5 A3：tasks.partner_heartbeat 端到端测试（真实 DB 行 + mock 渠道 provider）。

验证：真实到期信号触发推送 → 经事件总线 → mock provider 发送成功 → 推送流水
落库；第二次心跳因去重不重复发送。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.models import User, UserRole, WrongQuestion


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def due_student(db):
    now = datetime.now(timezone.utc)
    sid = uuid.uuid4()
    db.add(User(id=sid, role=UserRole.student, name="学生心跳", created_at=now))
    await db.flush()
    for _ in range(11):
        db.add(
            WrongQuestion(
                student_id=sid, fsrs_due=now - timedelta(hours=1), fsrs_state="review"
            )
        )
    await db.commit()
    await db.execute(
        text(
            "INSERT INTO agent.partner_channel_bindings (student_id, channel, target, enabled) "
            "VALUES (:sid, 'wecom', 'https://example.invalid/wh/heartbeat', true)"
        ),
        {"sid": sid},
    )
    await db.commit()

    yield sid

    await db.execute(
        text("DELETE FROM agent.partner_push_log WHERE student_id = :sid"), {"sid": sid}
    )
    await db.execute(
        text("DELETE FROM agent.partner_channel_bindings WHERE student_id = :sid"),
        {"sid": sid},
    )
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.mark.asyncio
async def test_heartbeat_sends_once_and_records_push_log(due_student, db, monkeypatch):
    monkeypatch.setenv("WECOM_PROVIDER", "mock")
    from tasks.partner_heartbeat import _run_heartbeat

    await _run_heartbeat()

    rows = (
        await db.execute(
            text(
                "SELECT channel, event_type FROM agent.partner_push_log "
                "WHERE student_id = :sid"
            ),
            {"sid": due_student},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == "wecom"
    assert rows[0][1] == "review_due"


@pytest.mark.asyncio
async def test_heartbeat_second_run_same_day_does_not_duplicate(
    due_student, db, monkeypatch
):
    monkeypatch.setenv("WECOM_PROVIDER", "mock")
    from tasks.partner_heartbeat import _run_heartbeat

    await _run_heartbeat()
    await _run_heartbeat()

    rows = (
        await db.execute(
            text("SELECT count(*) FROM agent.partner_push_log WHERE student_id = :sid"),
            {"sid": due_student},
        )
    ).scalar_one()
    assert rows == 1
