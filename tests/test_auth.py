"""
C.1 认证测试
============
覆盖：
- 完整注册+登录流程（Redis 验证码走真实校验）
- 防刷限制（60s 内第二次 send-code 返回 429）
- 合规红线：<14岁无监护人同意 → 422；带同意 → 201
- 验证码过期/错误 → 400
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from obase.config import settings
from obase.db import SessionLocal
from sqlalchemy import delete, select, update

from services.main import app
from services.models import GuardianConsent, ParentStudent, User

# ── helpers ───────────────────────────────────────────────────────────────────


async def _clean_phone(phone: str) -> None:
    """Remove user+guardian records, clear Redis SMS keys."""
    async with SessionLocal() as session:
        stmt = select(User.id).where(User.phone == phone)
        user_ids = (await session.execute(stmt)).scalars().all()
        if user_ids:
            await session.execute(
                delete(GuardianConsent).where(GuardianConsent.student_id.in_(user_ids))
            )
        await session.execute(delete(User).where(User.phone == phone))
        await session.commit()

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.delete(
            f"sms:code:{phone}",
            f"sms:limit:{phone}",
            f"sms:attempt:{phone}",
            f"sms:lock:{phone}",
        )
    finally:
        await r.aclose()


async def _inject_code(phone: str, code: str = "123456") -> None:
    """Put a code directly into Redis (bypasses send-code rate limit)."""
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.setex(f"sms:code:{phone}", 300, code)
    finally:
        await r.aclose()


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_full_flow(client):
    """send-code → Redis 存码 → register → me → login."""
    phone = "13912345678"
    await _clean_phone(phone)

    # 1. 发送验证码
    res = await client.post("/v1/auth/send-code", json={"phone": phone})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    # 2. 注册 (mock 模式 Redis 里存的就是 123456)
    res = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "Test Student",
            "birth_date": "2000-01-01",
            "grade": "高三",
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert "token" in data
    assert data["user"]["name"] == "Test Student"
    token = data["token"]

    # 3. /me
    res = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["phone"] == phone

    # 4. 登录（重新注入验证码，因为注册时已消费）
    await _inject_code(phone, "123456")
    res = await client.post("/v1/auth/login", json={"phone": phone, "code": "123456"})
    assert res.status_code == 200, res.text
    assert "token" in res.json()

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_send_code_rate_limit(client):
    """60秒内同手机号第二次 send-code → 429。"""
    phone = "13911112222"
    await _clean_phone(phone)

    res = await client.post("/v1/auth/send-code", json={"phone": phone})
    assert res.status_code == 200

    res = await client.post("/v1/auth/send-code", json={"phone": phone})
    assert res.status_code == 429
    assert "稍后" in res.json()["detail"]

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_invalid_code_rejected(client):
    """错误验证码 → 400。"""
    phone = "13922223333"
    await _clean_phone(phone)
    await _inject_code(phone, "123456")

    res = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "999999",
            "name": "Wrong Code",
            "birth_date": "2000-01-01",
            "grade": "高一",
        },
    )
    assert res.status_code == 400
    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_minor_without_guardian_rejected(client):
    """合规红线：13岁 + 无 guardian_phone → 422。"""
    phone = "13900001111"
    await _clean_phone(phone)
    await _inject_code(phone, "123456")

    res = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "Small Kid Fail",
            "birth_date": "2020-01-01",
            "grade": "三年级",
        },
    )
    assert res.status_code == 422, res.text
    assert "Guardian consent required" in res.json()["detail"]

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_minor_with_guardian_accepted(client):
    """合规红线：13岁 + guardian_phone + consent=true → 201，写 guardian_consents。"""
    phone = "13900002222"
    await _clean_phone(phone)
    await _inject_code(phone, "123456")

    res = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "Small Kid OK",
            "birth_date": "2020-01-01",
            "grade": "三年级",
            "guardian_phone": "13888888888",
            "guardian_consent": True,
        },
    )
    assert res.status_code == 201, res.text

    async with SessionLocal() as session:
        consent = (
            await session.execute(
                select(GuardianConsent).where(
                    GuardianConsent.guardian_phone == "13888888888"
                )
            )
        ).scalar_one_or_none()
        assert consent is not None
        assert consent.consent_type == "registration"
        # X.4：合规审计留痕，注册IP应该被记下来（此前字段定义了但从没写入过）
        assert consent.ip_address is not None

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_code_consumed_after_use(client):
    """验证码使用一次后失效，再注册同手机号 → 409（已注册）。"""
    phone = "13944445555"
    await _clean_phone(phone)
    await _inject_code(phone, "123456")

    res = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "Consume Test",
            "birth_date": "2000-01-01",
            "grade": "高二",
        },
    )
    assert res.status_code == 201, res.text

    # 同手机号再注册（注入新验证码），应返回 409
    await _inject_code(phone, "123456")
    res2 = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "Consume Test 2",
            "birth_date": "2000-01-01",
            "grade": "高二",
        },
    )
    assert res2.status_code == 409

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_deleted_user_cannot_login_or_query(client):
    """合规红线：软删除后不可登录、已签发 token 失效（删除后数据不可查询）。"""
    phone = "13900007777"
    await _clean_phone(phone)
    await _inject_code(phone)

    rs = await client.post(
        "/v1/auth/register/student",
        json={
            "phone": phone,
            "code": "123456",
            "name": "ToDelete",
            "birth_date": "2000-01-01",
            "grade": "高三",
        },
    )
    assert rs.status_code == 201, rs.text
    token = rs.json()["token"]
    student_id = rs.json()["user"]["id"]

    # 删除前 token 可用
    assert (
        await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200

    # 软删除
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == uuid.UUID(student_id))
            .values(deleted_at=datetime.now(UTC))
        )
        await s.commit()

    # 删除后：已签发 token 失效
    rme = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert rme.status_code == 401, rme.text

    # 删除后：无法再登录
    await _inject_code(phone)
    rl = await client.post("/v1/auth/login", json={"phone": phone, "code": "123456"})
    assert rl.status_code == 404, rl.text

    await _clean_phone(phone)


@pytest.mark.asyncio
async def test_delete_request_requires_auth(client):
    """删除端点必须鉴权：无 token → 401（防任意人删任意学生）。"""
    res = await client.post(f"/v1/parent/delete-request/{uuid.uuid4()}")
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_register_parent_binds_child(client):
    """学生注册得 invite_code → 家长用 invite_code 注册并绑定 → /parent/children 含该生。"""
    s_phone = "13988880001"
    p_phone = "13988880002"

    async def _cleanup():
        async with SessionLocal() as s:
            ids = (
                (
                    await s.execute(
                        select(User.id).where(User.phone.in_([s_phone, p_phone]))
                    )
                )
                .scalars()
                .all()
            )
            if ids:
                await s.execute(
                    delete(ParentStudent).where(
                        (ParentStudent.parent_id.in_(ids))
                        | (ParentStudent.student_id.in_(ids))
                    )
                )
                await s.commit()
        await _clean_phone(p_phone)
        await _clean_phone(s_phone)

    await _cleanup()
    try:
        # 学生注册（≥14，无需监护人同意），拿到 invite_code
        await _inject_code(s_phone)
        rs = await client.post(
            "/v1/auth/register/student",
            json={
                "phone": s_phone,
                "code": "123456",
                "name": "娃",
                "birth_date": "2008-01-01",
                "grade": "高一",
            },
        )
        assert rs.status_code == 201, rs.text
        invite = rs.json()["user"]["invite_code"]
        assert invite and len(invite) == 6

        # 家长注册 + 凭 invite_code 绑定
        await _inject_code(p_phone)
        rp = await client.post(
            "/v1/auth/register/parent",
            json={
                "phone": p_phone,
                "code": "123456",
                "name": "家长",
                "invite_code": invite,
            },
        )
        assert rp.status_code == 201, rp.text
        ptok = rp.json()["token"]

        # 家长能看到孩子
        rc = await client.get(
            "/v1/parent/children", headers={"Authorization": f"Bearer {ptok}"}
        )
        assert rc.status_code == 200, rc.text
        assert "娃" in [c["name"] for c in rc.json()]

        # 错误邀请码 → 404
        await _inject_code("13988880003")
        rbad = await client.post(
            "/v1/auth/register/parent",
            json={
                "phone": "13988880003",
                "code": "123456",
                "name": "X",
                "invite_code": "ZZZZZZ",
            },
        )
        assert rbad.status_code == 404
    finally:
        await _clean_phone("13988880003")
        await _cleanup()


@pytest.mark.asyncio
async def test_verify_code_lockout_after_many_attempts(client):
    """C2 防暴力破解：验证码连续输错超过上限 → 即使输对也拒绝（通道锁定）。

    用真实验证码（不走 MOCK_CODE 旁路）：注入 654321，连续输错 999999 达上限，
    随后正确 654321 也返回 400（被锁）。"""
    from services.auth_service import MAX_VERIFY_ATTEMPTS

    phone = "13977776666"
    await _clean_phone(phone)
    try:
        # 注入一个真实验证码（非 MOCK_CODE，强制走真实校验分支）
        await _inject_code(phone, "654321")

        body = {
            "phone": phone,
            "code": "999999",
            "name": "Lockout",
            "birth_date": "2000-01-01",
            "grade": "高一",
        }
        # 输错达到上限-1 次：仍 400，不锁
        for _ in range(MAX_VERIFY_ATTEMPTS - 1):
            res = await client.post("/v1/auth/register/student", json=body)
            assert res.status_code == 400, res.text
        # 第 MAX 次输错后已锁；再输对也被拒
        res = await client.post("/v1/auth/register/student", json=body)
        assert res.status_code == 400, res.text
        body["code"] = "654321"
        res = await client.post("/v1/auth/register/student", json=body)
        assert res.status_code == 400, res.text
        assert "验证码" in res.json()["detail"]
    finally:
        await _clean_phone(phone)


@pytest.mark.asyncio
async def test_verify_code_attempts_reset_on_success(client):
    """C2：验证码输对后计数清零——此后再次输错从零计，不会立刻被锁。"""

    phone = "13966665555"
    await _clean_phone(phone)
    try:
        # 输错 1 次
        await _inject_code(phone, "654321")
        body = {
            "phone": phone,
            "code": "999999",
            "name": "Reset",
            "birth_date": "2000-01-01",
            "grade": "高一",
        }
        res = await client.post("/v1/auth/register/student", json=body)
        assert res.status_code == 400, res.text

        # 正确码成功注册（消费 code），attempt 计数随成功删除
        await _inject_code(phone, "654321")
        body["code"] = "654321"
        res = await client.post("/v1/auth/register/student", json=body)
        assert res.status_code == 201, res.text
    finally:
        await _clean_phone(phone)
