"""W5 A3/PA-3：oskill.partner_dispatch —— 真实 FSRS 信号驱动 + 节流去重。

用真实 DB 行（同 tests/test_partner_tasks.py 的 fixture 写法）：验证只有真实
超过阈值的到期错题数才会触发候选（PA-3：推送来自真实 FSRS 信号，非编造），
且同一天内已推送过的不会重复推送（节流/去重）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from oskill.partner_dispatch import compute_partner_pushes
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
async def bound_students(db):
    """① due_id：11 道到期错题 + wecom 绑定（该被推送）；② quiet_id：0 道到期错题
    + wecom 绑定（不该被推送——真实信号不足阈值）。"""
    now = datetime.now(timezone.utc)
    due_id, quiet_id = uuid.uuid4(), uuid.uuid4()

    db.add(User(id=due_id, role=UserRole.student, name="学生due", created_at=now))
    db.add(User(id=quiet_id, role=UserRole.student, name="学生quiet", created_at=now))
    await db.flush()

    for _ in range(11):
        db.add(
            WrongQuestion(
                student_id=due_id,
                fsrs_due=now - timedelta(hours=1),
                fsrs_state="review",
            )
        )
    await db.commit()

    await db.execute(
        text(
            "INSERT INTO agent.partner_channel_bindings (student_id, channel, target, enabled) "
            "VALUES (:sid, 'wecom', 'https://example.invalid/wh/1', true), "
            "(:qid, 'wecom', 'https://example.invalid/wh/2', true)"
        ),
        {"sid": due_id, "qid": quiet_id},
    )
    await db.commit()

    yield {"due": due_id, "quiet": quiet_id}

    await db.execute(
        text("DELETE FROM agent.partner_push_log WHERE student_id IN (:a, :b)"),
        {"a": due_id, "b": quiet_id},
    )
    await db.execute(
        text("DELETE FROM agent.partner_channel_bindings WHERE student_id IN (:a, :b)"),
        {"a": due_id, "b": quiet_id},
    )
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == due_id))
    await db.execute(delete(User).where(User.id.in_([due_id, quiet_id])))
    await db.commit()


@pytest.mark.asyncio
async def test_only_student_over_real_due_threshold_gets_a_push(bound_students, db):
    pushes = await compute_partner_pushes(db)
    student_ids = {p["student_id"] for p in pushes}
    assert bound_students["due"] in student_ids
    assert bound_students["quiet"] not in student_ids


@pytest.mark.asyncio
async def test_push_text_uses_real_name_and_due_count(bound_students, db):
    pushes = await compute_partner_pushes(db)
    due_push = next(p for p in pushes if p["student_id"] == bound_students["due"])
    assert "学生due" in due_push["text"]
    assert "11" in due_push["text"]
    assert due_push["channel"] == "wecom"
    assert due_push["target"] == "https://example.invalid/wh/1"


@pytest.mark.asyncio
async def test_dedup_suppresses_repeat_push_same_day(bound_students, db):
    pushes = await compute_partner_pushes(db)
    due_push = next(p for p in pushes if p["student_id"] == bound_students["due"])

    # 模拟 tasks/partner_heartbeat.py 记录一次推送流水
    await db.execute(
        text(
            "INSERT INTO agent.partner_push_log (student_id, channel, event_type, dedup_key) "
            "VALUES (:sid, :ch, :et, :dk)"
        ),
        {
            "sid": due_push["student_id"],
            "ch": due_push["channel"],
            "et": due_push["event_type"],
            "dk": due_push["dedup_key"],
        },
    )
    await db.commit()

    pushes_again = await compute_partner_pushes(db)
    assert bound_students["due"] not in {p["student_id"] for p in pushes_again}
