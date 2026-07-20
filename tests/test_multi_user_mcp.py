"""W5 Part B 端到端（真实 HTTP，同 tests/test_authz.py 的 fixture 写法）。

MB-1 per-user 隔离：学生 A 查不到学生 B 的授权/审计（403）。
MB-2 admin 授权：deny-by-default——未授权工具被拒；admin 授权后放行。
MB-3 审计：BindPartnerChannel 成功后落一条审计记录。
MB-5 IDOR：非本人/非 admin 访问他人 GetUserGrant/GetAuditLog → 403。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import User, UserRole


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


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
    admin_id, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))

    db.add(User(id=admin_id, role=UserRole.student, name="管理员"))
    db.add(User(id=a, role=UserRole.student, name="学生A"))
    db.add(User(id=b, role=UserRole.student, name="学生B"))
    await db.commit()

    yield {"admin": admin_id, "a": a, "b": b}

    ids = [admin_id, a, b]
    await db.execute(
        text("DELETE FROM agent.audit_log WHERE student_id = ANY(:ids)"), {"ids": ids}
    )
    await db.execute(
        text("DELETE FROM agent.partner_channel_bindings WHERE student_id = ANY(:ids)"),
        {"ids": ids},
    )
    await db.execute(
        text("DELETE FROM agent.user_grants WHERE student_id = ANY(:ids)"), {"ids": ids}
    )
    await db.execute(delete(User).where(User.id.in_(ids)))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_student_cannot_view_another_students_grant(actors, client):
    """MB-1/MB-5：A 查 B 的授权 → 403。"""
    resp = await client.post(
        "/mcp/GetUserGrant",
        json={"student_id": str(actors["b"])},
        headers=_h(actors["a"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_student_cannot_view_another_students_audit_log(actors, client):
    resp = await client.post(
        "/mcp/GetAuditLog",
        json={"student_id": str(actors["b"])},
        headers=_h(actors["a"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_bind_partner_channel_denied_without_grant(actors, client):
    """MB-2 deny-by-default：没有授权行时，绑定 Partner 渠道被拒。"""
    resp = await client.post(
        "/mcp/BindPartnerChannel",
        json={
            "student_id": str(actors["a"]),
            "channel": "wecom",
            "target": "https://example.invalid/wh/x",
        },
        headers=_h(actors["a"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_set_grant(actors, client):
    resp = await client.post(
        "/mcp/SetUserGrant",
        json={"student_id": str(actors["a"]), "enabled_tools": ["BindPartnerChannel"]},
        headers=_h(actors["a"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_grant_then_bind_succeeds_and_is_audited(actors, client, db):
    """MB-2 + MB-3：admin 授权后绑定成功，且落一条审计记录。"""
    grant_resp = await client.post(
        "/mcp/SetUserGrant",
        json={
            "student_id": str(actors["a"]),
            "enabled_tools": ["BindPartnerChannel"],
        },
        headers=_h(actors["admin"]),
    )
    assert grant_resp.status_code == 200

    bind_resp = await client.post(
        "/mcp/BindPartnerChannel",
        json={
            "student_id": str(actors["a"]),
            "channel": "wecom",
            "target": "https://example.invalid/wh/x",
        },
        headers=_h(actors["a"]),
    )
    assert bind_resp.status_code == 200
    assert bind_resp.json()["bound"] is True

    audit_resp = await client.post(
        "/mcp/GetAuditLog",
        json={"student_id": str(actors["a"])},
        headers=_h(actors["a"]),
    )
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    assert any(e["action"] == "bind_partner_channel" for e in entries)
