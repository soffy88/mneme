"""W5 Part B MB-2：obase.user_grants —— admin-curated 授权，deny-by-default。

真实 DB 行（同既有 fixture 写法），验证：无授权行 = 拒绝一切；admin 设置授权后
按白名单放行；非 admin 调 set_grant 直接拒绝；actor 是 admin 时任何工具/模型
都放行（不受白名单限制）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.user_grants import (
    GrantNotAuthorizedError,
    get_grant,
    is_model_authorized,
    is_tool_authorized,
    set_grant,
)
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
    db.add(User(id=student_id, role=UserRole.student, name="学生G"))
    await db.commit()

    yield {"admin": admin_id, "student": student_id}

    await db.execute(
        text("DELETE FROM agent.audit_log WHERE student_id = ANY(:ids)"),
        {"ids": [admin_id, student_id]},
    )
    await db.execute(
        text("DELETE FROM agent.user_grants WHERE student_id = ANY(:ids)"),
        {"ids": [admin_id, student_id]},
    )
    await db.execute(delete(User).where(User.id.in_([admin_id, student_id])))
    await db.commit()


class _Actor:
    def __init__(self, id):
        self.id = id


@pytest.mark.asyncio
async def test_no_grant_row_denies_everything(actors, db):
    grant = await get_grant(db, actors["student"])
    assert grant["enabled_tools"] is None
    assert grant["allowed_models"] is None
    assert await is_tool_authorized(db, actors["student"], "AnyTool") is False
    assert await is_model_authorized(db, actors["student"], "any-model") is False


@pytest.mark.asyncio
async def test_non_admin_cannot_set_grant(actors, db):
    with pytest.raises(GrantNotAuthorizedError):
        await set_grant(
            db,
            admin_user=_Actor(actors["student"]),
            student_id=actors["student"],
            enabled_tools=["BindPartnerChannel"],
        )


@pytest.mark.asyncio
async def test_admin_can_grant_and_whitelist_is_enforced(actors, db):
    await set_grant(
        db,
        admin_user=_Actor(actors["admin"]),
        student_id=actors["student"],
        enabled_tools=["BindPartnerChannel"],
        allowed_models=["qwen"],
    )
    await db.commit()

    assert await is_tool_authorized(db, actors["student"], "BindPartnerChannel") is True
    assert await is_tool_authorized(db, actors["student"], "SomeOtherTool") is False
    assert await is_model_authorized(db, actors["student"], "qwen") is True
    assert await is_model_authorized(db, actors["student"], "deepseek") is False


@pytest.mark.asyncio
async def test_admin_actor_bypasses_whitelist(actors, db):
    """actor=admin 时任何工具都放行，即便该学生自己完全没有授权行。"""
    ok = await is_tool_authorized(
        db, actors["student"], "AnyTool", actor=_Actor(actors["admin"])
    )
    assert ok is True
