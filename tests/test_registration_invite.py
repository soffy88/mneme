"""邀请制学生注册 + 统一年龄门禁（P0-6 / P0-7）。

覆盖：
1. 管理员才能生成/吊销邀请码；
2. 邀请码注册不依赖邮件/短信（REGISTRATION_OPEN=0 也可用）；
3. 邀请码单次使用，重复/过期/吊销都拒绝；
4. 所有学生注册路径都会把 birth_date 落库；
5. <14 岁必须有监护人邮箱 + 明确同意（邀请码/用户名/邮箱路径共用闸门）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from obase.auth import create_access_token
from obase.config import settings
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.main import app
from services.models import GuardianConsent, RegistrationInvite, User, UserRole


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


async def _make_user(db: AsyncSession, *, name: str = "邀请测试") -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"inv-{uuid.uuid4().hex[:10]}@example.invalid",
        name=name,
        role=UserRole.student,
    )
    db.add(user)
    await db.commit()
    return user


def _token(user: User) -> str:
    return create_access_token({"sub": str(user.id), "role": user.role.value})


async def _cleanup(db: AsyncSession, user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    await db.execute(
        delete(RegistrationInvite).where(
            (RegistrationInvite.created_by.in_(user_ids))
            | (RegistrationInvite.student_id.in_(user_ids))
        )
    )
    await db.execute(delete(GuardianConsent).where(GuardianConsent.student_id.in_(user_ids)))
    await db.execute(delete(User).where(User.id.in_(user_ids)))
    await db.commit()


async def _create_invite(client: AsyncClient, token: str, **overrides) -> dict:
    payload = {"count": 1, "expires_in_days": 7, "note": "pytest"}
    payload.update(overrides)
    r = await client.post(
        "/v1/admin/invitations",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["invitations"][0]


@pytest.mark.asyncio
async def test_only_admin_can_create_invites(client, db, monkeypatch):
    admin = await _make_user(db)
    normal = await _make_user(db)
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin.id))
    try:
        denied = await client.post(
            "/v1/admin/invitations",
            json={"count": 1},
            headers={"Authorization": f"Bearer {_token(normal)}"},
        )
        assert denied.status_code == 403

        created = await _create_invite(client, _token(admin))
        assert created["code"].startswith("SXJ-")
        assert created["expires_at"]
    finally:
        await _cleanup(db, [admin.id, normal.id])


@pytest.mark.asyncio
async def test_invite_registration_without_any_email_provider(client, db, monkeypatch):
    """邀请码注册在 REGISTRATION_OPEN=0 / EMAIL_PROVIDER=mock 下仍可用。"""
    admin = await _make_user(db)
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin.id))
    monkeypatch.setenv("REGISTRATION_OPEN", "0")
    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    invite = await _create_invite(client, _token(admin))
    username = f"invite-{uuid.uuid4().hex[:8]}"
    student_id: uuid.UUID | None = None
    try:
        r = await client.post(
            "/v1/auth/register/student-invite",
            json={
                "invitation_code": invite["code"],
                "username": username,
                "password": "Mneme-Secure-Test-2026",
                "name": "邀请码学生",
                "birth_date": "2010-05-06",
                "grade": "G9",
            },
        )
        assert r.status_code == 201, r.text
        student_id = uuid.UUID(r.json()["user"]["id"])
        assert r.json()["token"]

        user = (
            await db.execute(select(User).where(User.id == student_id))
        ).scalar_one()
        assert user.birth_date == date(2010, 5, 6)
        assert user.invite_code  # 家长绑定用的 6 位码

        row = (
            await db.execute(
                select(RegistrationInvite).where(RegistrationInvite.code == invite["code"])
            )
        ).scalar_one()
        assert row.student_id == student_id
        assert row.used_at is not None

        # 单次使用：同一码不能注册第二个学生。
        again = await client.post(
            "/v1/auth/register/student-invite",
            json={
                "invitation_code": invite["code"],
                "username": f"invite-{uuid.uuid4().hex[:8]}",
                "password": "Mneme-Secure-Test-2026",
                "name": "重复使用",
                "birth_date": "2010-05-06",
                "grade": "G9",
            },
        )
        assert again.status_code == 400
    finally:
        await _cleanup(db, [admin.id] + ([student_id] if student_id else []))


@pytest.mark.asyncio
async def test_expired_and_revoked_invites_rejected(client, db, monkeypatch):
    admin = await _make_user(db)
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin.id))
    expired = RegistrationInvite(
        code=f"SXJ-EXP{uuid.uuid4().hex[:2].upper()}-TEST",
        created_by=admin.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    revoked = RegistrationInvite(
        code=f"SXJ-REV{uuid.uuid4().hex[:2].upper()}-TEST",
        created_by=admin.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=datetime.now(UTC),
    )
    db.add_all([expired, revoked])
    await db.commit()
    try:
        for code in (expired.code, revoked.code):
            r = await client.post(
                "/v1/auth/register/student-invite",
                json={
                    "invitation_code": code,
                    "username": f"invite-{uuid.uuid4().hex[:8]}",
                    "password": "Mneme-Secure-Test-2026",
                    "name": "无效邀请",
                    "birth_date": "2010-05-06",
                    "grade": "G9",
                },
            )
            assert r.status_code == 400, r.text
    finally:
        await _cleanup(db, [admin.id])


@pytest.mark.asyncio
async def test_invite_minor_requires_guardian_consent(client, db, monkeypatch):
    admin = await _make_user(db)
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin.id))
    invite = await _create_invite(client, _token(admin))
    student_ids: list[uuid.UUID] = []
    try:
        rejected = await client.post(
            "/v1/auth/register/student-invite",
            json={
                "invitation_code": invite["code"],
                "username": f"kid-{uuid.uuid4().hex[:8]}",
                "password": "Mneme-Secure-Test-2026",
                "name": "小朋友",
                "birth_date": "2020-01-01",
                "grade": "三年级",
            },
        )
        assert rejected.status_code == 422
        assert "Guardian consent" in rejected.json()["detail"]

        invite2 = await _create_invite(client, _token(admin))
        accepted = await client.post(
            "/v1/auth/register/student-invite",
            json={
                "invitation_code": invite2["code"],
                "username": f"kid-{uuid.uuid4().hex[:8]}",
                "password": "Mneme-Secure-Test-2026",
                "name": "小朋友OK",
                "birth_date": "2020-01-01",
                "grade": "三年级",
                "guardian_email": "guardian@qq.com",
                "guardian_consent": True,
            },
        )
        assert accepted.status_code == 201, accepted.text
        sid = uuid.UUID(accepted.json()["user"]["id"])
        student_ids.append(sid)
        consent = (
            await db.execute(
                select(GuardianConsent).where(GuardianConsent.student_id == sid)
            )
        ).scalar_one_or_none()
        assert consent is not None
        assert consent.guardian_email == "guardian@qq.com"
    finally:
        await _cleanup(db, [admin.id, *student_ids])


@pytest.mark.asyncio
async def test_minor_username_registration_needs_guardian(client, db, monkeypatch):
    """用户名路径同样受统一闸门约束：无监护人同意 422，带同意可注册且生日落库。"""
    monkeypatch.setenv("REGISTRATION_OPEN", "1")
    student_ids: list[uuid.UUID] = []
    try:
        rejected = await client.post(
            "/v1/auth/register/student-account",
            json={
                "username": f"kid-{uuid.uuid4().hex[:8]}",
                "password": "Mneme-Secure-Test-2026",
                "name": "小孩",
                "birth_date": "2020-01-01",
                "grade": "三年级",
            },
        )
        assert rejected.status_code == 422

        accepted = await client.post(
            "/v1/auth/register/student-account",
            json={
                "username": f"kid-{uuid.uuid4().hex[:8]}",
                "password": "Mneme-Secure-Test-2026",
                "name": "小孩OK",
                "birth_date": "2020-01-01",
                "grade": "三年级",
                "guardian_email": "guardian2@qq.com",
                "guardian_consent": True,
            },
        )
        assert accepted.status_code == 201, accepted.text
        sid = uuid.UUID(accepted.json()["user"]["id"])
        student_ids.append(sid)
        user = (await db.execute(select(User).where(User.id == sid))).scalar_one()
        assert user.birth_date == date(2020, 1, 1)
        consent = (
            await db.execute(
                select(GuardianConsent).where(GuardianConsent.student_id == sid)
            )
        ).scalar_one_or_none()
        assert consent is not None
    finally:
        await _cleanup(db, student_ids)


@pytest.mark.asyncio
async def test_invite_revoke_endpoint(client, db, monkeypatch):
    admin = await _make_user(db)
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin.id))
    invite = await _create_invite(client, _token(admin))
    try:
        r = await client.post(
            f"/v1/admin/invitations/{invite['id']}/revoke",
            headers={"Authorization": f"Bearer {_token(admin)}"},
        )
        assert r.status_code == 200, r.text
        listing = await client.get(
            "/v1/admin/invitations",
            headers={"Authorization": f"Bearer {_token(admin)}"},
        )
        assert listing.status_code == 200
        statuses = {row["id"]: row["status"] for row in listing.json()["invitations"]}
        assert statuses[invite["id"]] == "revoked"
    finally:
        await _cleanup(db, [admin.id])
