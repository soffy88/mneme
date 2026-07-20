"""W5 Part B MB-3：obase.audit_log —— 用户操作审计。

真实 DB 行：log_usage 记非 admin 操作、跳过 admin 自身操作（减少噪音）；
log_admin_action 总是记；写审计失败不抛异常（fail-safe，不能拖垮正常请求）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.audit_log import get_audit_log, log_admin_action, log_usage
from obase.config import settings
from services.models import User, UserRole


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
async def actors(db, monkeypatch):
    admin_id, student_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))

    db.add(User(id=admin_id, role=UserRole.student, name="管理员"))
    db.add(User(id=student_id, role=UserRole.student, name="学生H"))
    await db.commit()

    yield {"admin": admin_id, "student": student_id}

    await db.execute(
        text("DELETE FROM agent.audit_log WHERE student_id = ANY(:ids)"),
        {"ids": [admin_id, student_id]},
    )
    await db.execute(delete(User).where(User.id.in_([admin_id, student_id])))
    await db.commit()


class _Actor:
    def __init__(self, id):
        self.id = id


@pytest.mark.asyncio
async def test_log_usage_records_non_admin_action(actors, db):
    await log_usage(
        db,
        actor=_Actor(actors["student"]),
        action="bind_partner_channel",
        resource_type="partner_channel",
        resource_id="wecom",
    )
    await db.commit()

    entries = await get_audit_log(db, actors["student"])
    assert len(entries) == 1
    assert entries[0]["action"] == "bind_partner_channel"
    assert entries[0]["resource_id"] == "wecom"


@pytest.mark.asyncio
async def test_log_usage_skips_admin_self_action(actors, db):
    await log_usage(db, actor=_Actor(actors["admin"]), action="whatever")
    await db.commit()

    entries = await get_audit_log(db, actors["admin"])
    assert entries == []


@pytest.mark.asyncio
async def test_log_admin_action_always_records(actors, db):
    await log_admin_action(
        db,
        admin_user=_Actor(actors["admin"]),
        action="set_user_grant",
        target_student_id=actors["student"],
    )
    await db.commit()

    entries = await get_audit_log(db, actors["admin"])
    assert len(entries) == 1
    assert entries[0]["action"] == "set_user_grant"
    assert entries[0]["resource_id"] == str(actors["student"])


@pytest.mark.asyncio
async def test_write_failure_does_not_raise(actors, db):
    """审计写失败必须吞掉异常——不能因为审计挂了就让正常请求跟着炸。

    用 monkeypatch.context() 局部作用域，patch 在本测试体结束时就还原——
    不能用普通 monkeypatch 夹具参数，那样 patch 会一直留到 actors 夹具自己的
    teardown（也要用同一个 db.execute 做清理 DELETE）才还原，把 teardown 也
    炸了。
    """
    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("db exploded")

        mp.setattr(db, "execute", _boom)
        await log_usage(
            db, actor=_Actor(actors["student"]), action="whatever"
        )  # 不应抛
