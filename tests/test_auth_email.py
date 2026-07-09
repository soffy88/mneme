"""邮箱注册/登录（新主标识）。手机号流程不动，这里覆盖 email 平行路径：
发码/注册学生/合规红线(<14监护同意，改用guardian_email)/登录/查重/家长绑定。
mock 模式(EMAIL_PROVIDER 默认非smtp) MOCK_CODE=123456 旁路，无需真发邮件。"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.main import app
from services.models import GuardianConsent, ParentStudent, User


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
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _clean_email(db: AsyncSession, email: str) -> None:
    ids = (await db.execute(select(User.id).where(User.email == email))).scalars().all()
    if ids:
        await db.execute(
            delete(GuardianConsent).where(GuardianConsent.student_id.in_(ids))
        )
        await db.execute(
            delete(ParentStudent).where(
                (ParentStudent.parent_id.in_(ids)) | (ParentStudent.student_id.in_(ids))
            )
        )
    await db.execute(delete(User).where(User.email == email))
    await db.commit()


@pytest.mark.asyncio
async def test_send_email_code_ok(client):
    email = f"s-{uuid.uuid4().hex[:8]}@qq.com"  # 唯一，避开60s防刷键跨测试残留
    r = await client.post("/v1/auth/send-email-code", json={"email": email})
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_invalid_email_rejected(client):
    r = await client.post("/v1/auth/send-email-code", json={"email": "not-an-email"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_student_email_full_flow(client, db):
    email = f"stu-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(db, email)
    try:
        r = await client.post(
            "/v1/auth/register/student-email",
            json={
                "email": email,
                "code": "123456",
                "name": "邮箱学生",
                "birth_date": "2008-01-01",
                "grade": "G10",
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["user"]["email"] == email
        assert "token" in data and data["user"]["invite_code"]

        # 登录
        r = await client.post(
            "/v1/auth/login-email", json={"email": email, "code": "123456"}
        )
        assert r.status_code == 200
        assert "token" in r.json()

        # 查重
        r = await client.post(
            "/v1/auth/register/student-email",
            json={
                "email": email,
                "code": "123456",
                "name": "又一个",
                "birth_date": "2008-01-01",
                "grade": "G10",
            },
        )
        assert r.status_code == 409
    finally:
        await _clean_email(db, email)


@pytest.mark.asyncio
async def test_minor_email_without_guardian_rejected(client, db):
    """合规红线：<14 邮箱注册无监护人邮箱+同意 → 422。"""
    email = f"kid-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(db, email)
    try:
        r = await client.post(
            "/v1/auth/register/student-email",
            json={
                "email": email,
                "code": "123456",
                "name": "小朋友",
                "birth_date": "2020-01-01",  # <14
                "grade": "三年级",
            },
        )
        assert r.status_code == 422
    finally:
        await _clean_email(db, email)


@pytest.mark.asyncio
async def test_minor_email_with_guardian_accepted(client, db):
    """<14 + guardian_email + consent → 201，写 guardian_consents(guardian_email)。"""
    email = f"kid-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(db, email)
    try:
        r = await client.post(
            "/v1/auth/register/student-email",
            json={
                "email": email,
                "code": "123456",
                "name": "小朋友OK",
                "birth_date": "2020-01-01",
                "grade": "三年级",
                "guardian_email": "parent@qq.com",
                "guardian_consent": True,
            },
        )
        assert r.status_code == 201, r.text
        sid = uuid.UUID(r.json()["user"]["id"])
        consent = (
            await db.execute(
                select(GuardianConsent).where(GuardianConsent.student_id == sid)
            )
        ).scalar_one_or_none()
        assert consent is not None
        assert consent.guardian_email == "parent@qq.com"
        assert consent.ip_address is not None  # 注册IP留痕
    finally:
        await _clean_email(db, email)


@pytest.mark.asyncio
async def test_register_parent_email_binds_child(client, db):
    """家长邮箱注册凭 invite_code 绑定孩子。"""
    child_email = f"child-{uuid.uuid4().hex[:8]}@qq.com"
    parent_email = f"parent-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(db, child_email)
    await _clean_email(db, parent_email)
    try:
        r = await client.post(
            "/v1/auth/register/student-email",
            json={
                "email": child_email,
                "code": "123456",
                "name": "娃",
                "birth_date": "2008-01-01",
                "grade": "G10",
            },
        )
        assert r.status_code == 201, r.text
        invite = r.json()["user"]["invite_code"]

        r = await client.post(
            "/v1/auth/register/parent-email",
            json={
                "email": parent_email,
                "code": "123456",
                "name": "家长",
                "invite_code": invite,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["user"]["email"] == parent_email
    finally:
        await _clean_email(db, parent_email)
        await _clean_email(db, child_email)
