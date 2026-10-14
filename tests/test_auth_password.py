"""可选密码登录测试

覆盖四条安全不变量（每条都对应一个真实可利用的失败模式）：

1. password_hash 绝不进任何响应体 —— 加列到 ORM 模型后最容易犯的错。
2. "账号不存在" 与 "密码错误" 响应完全一致 —— 否则可枚举已注册邮箱。
3. password_hash IS NULL 的账号不能用空密码登录 —— 否则未设密码=任何密码可登。
4. 连续输错触发锁定 —— 否则密码通道可无限撞库。
"""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from obase.config import settings
from obase.db import SessionLocal
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.main import app
from services.models import User
from services.passwords import (
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_CHARS,
    PasswordPolicyError,
    hash_password,
    verify_password,
)


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


async def _clean_email(email: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.delete(
            f"email:code:{email}",
            f"email:limit:{email}",
            f"email:attempt:{email}",
            f"email:lock:{email}",
            f"password:fail:{email}",
            f"password:lock:{email}",
        )
    finally:
        await r.aclose()


async def _register(client, email: str, monkeypatch) -> str:
    monkeypatch.setenv("MNEME_ENV", "test")
    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    monkeypatch.setenv("MNEME_MOCK_CODE_ALLOWLIST", email)
    r = await client.post(
        "/v1/auth/register/student-email",
        json={
            "email": email,
            "code": "123456",
            "name": "密码测试",
            "birth_date": "2008-01-01",
            "grade": "G10",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["token"]


# ── 1. 哈希泄漏 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_password_hash_never_in_any_response(client, db, monkeypatch):
    """password_hash 不得出现在注册/登录/me 任何一个响应体里。"""
    email = f"leak-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(email)
    try:
        token = await _register(client, email, monkeypatch)

        bodies = [
            (await client.post("/v1/auth/login-email", json={"email": email, "code": "123456"})).text,
            (
                await client.post(
                    "/v1/auth/password",
                    json={"password": "sup3r-secret-pw"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).text,
            (await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).text,
            (
                await client.post(
                    "/v1/auth/login-password", json={"email": email, "password": "sup3r-secret-pw"}
                )
            ).text,
        ]
        for body in bodies:
            assert "password_hash" not in body, body
            assert "$2b$" not in body, body
            assert "sup3r-secret-pw" not in body, body
    finally:
        await _clean_email(email)


# ── 2. 不泄露账号是否存在 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_email_and_wrong_password_indistinguishable(client, db, monkeypatch):
    known = f"known-{uuid.uuid4().hex[:8]}@qq.com"
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(known)
    await _clean_email(unknown)
    try:
        token = await _register(client, known, monkeypatch)
        await client.post(
            "/v1/auth/password",
            json={"password": "sup3r-secret-pw"},
            headers={"Authorization": f"Bearer {token}"},
        )

        r_known = await client.post(
            "/v1/auth/login-password", json={"email": known, "password": "wrong-password-here"}
        )
        r_unknown = await client.post(
            "/v1/auth/login-password", json={"email": unknown, "password": "wrong-password-here"}
        )
        assert r_known.status_code == r_unknown.status_code == 401
        assert r_known.json() == r_unknown.json()
    finally:
        await _clean_email(known)
        await _clean_email(unknown)


# ── 3. 未设密码 ≠ 空密码可登录 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_without_password_cannot_log_in(client, db, monkeypatch):
    """password_hash IS NULL 的账号必须拒绝**所有**密码，包括空串。"""
    email = f"nopw-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(email)
    try:
        await _register(client, email, monkeypatch)
        for candidate in ["", " ", "x" * MIN_PASSWORD_CHARS, "123456"]:
            r = await client.post(
                "/v1/auth/login-password", json={"email": email, "password": candidate}
            )
            assert r.status_code == 401, (candidate, r.status_code, r.text)
    finally:
        await _clean_email(email)


@pytest.mark.asyncio
async def test_verify_password_rejects_null_hash():
    assert verify_password("anything", None) is False
    assert verify_password("", None) is False


# ── 4. 撞库锁定 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_password_login_lockout_after_max_attempts(client, db, monkeypatch):
    """连续输错到上限后锁定；且锁定只锁密码通道，验证码登录仍可用。"""
    email = f"lock-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(email)
    try:
        token = await _register(client, email, monkeypatch)
        await client.post(
            "/v1/auth/password",
            json={"password": "sup3r-secret-pw"},
            headers={"Authorization": f"Bearer {token}"},
        )

        from services.auth_service import PASSWORD_MAX_ATTEMPTS

        for _ in range(PASSWORD_MAX_ATTEMPTS):
            r = await client.post(
                "/v1/auth/login-password", json={"email": email, "password": "wrong-password-here"}
            )
            assert r.status_code == 401

        r = await client.post(
            "/v1/auth/login-password", json={"email": email, "password": "wrong-password-here"}
        )
        assert r.status_code == 429

        # 关键：锁定期间**正确**密码也应被拒（否则锁定形同虚设），
        # 但验证码通道不受影响，用户不会被锁死。
        r = await client.post(
            "/v1/auth/login-password", json={"email": email, "password": "sup3r-secret-pw"}
        )
        assert r.status_code == 429
        r = await client.post(
            "/v1/auth/login-email", json={"email": email, "code": "123456"}
        )
        assert r.status_code == 200, "密码锁定不应波及验证码通道"
    finally:
        await _clean_email(email)


# ── 5. 正常路径 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_password_login_success_and_code_login_still_works(client, db, monkeypatch):
    """设密码后：密码能登，验证码也仍能登（两条通道互不取代）。"""
    email = f"ok-{uuid.uuid4().hex[:8]}@qq.com"
    await _clean_email(email)
    try:
        token = await _register(client, email, monkeypatch)

        r = await client.post(
            "/v1/auth/password",
            json={"password": "sup3r-secret-pw"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

        r = await client.post(
            "/v1/auth/login-password", json={"email": email, "password": "sup3r-secret-pw"}
        )
        assert r.status_code == 200, r.text
        # 形状必须与 login_email 一致（id + name，不含 email/密码材料）。
        assert set(r.json()["user"]) == {"id", "name"}
        assert "token" in r.json()

        # 验证码通道仍在
        r = await client.post(
            "/v1/auth/login-email", json={"email": email, "code": "123456"}
        )
        assert r.status_code == 200

        # me 报告 has_password
        r = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.json()["has_password"] is True
    finally:
        await _clean_email(email)


@pytest.mark.asyncio
async def test_set_password_requires_auth(client, db):
    r = await client.post("/v1/auth/password", json={"password": "sup3r-secret-pw"})
    assert r.status_code in (401, 403)


# ── 6. 密码策略 ──────────────────────────────────────────────────────────────


def test_hash_password_policy_boundaries():
    with pytest.raises(PasswordPolicyError):
        hash_password("short")
    with pytest.raises(PasswordPolicyError):
        hash_password("")
    # 恰好 8 字节 / 恰好 72 字节都应通过
    assert hash_password("a" * MIN_PASSWORD_CHARS)
    assert hash_password("b" * MAX_PASSWORD_BYTES)
    with pytest.raises(PasswordPolicyError):
        hash_password("c" * (MAX_PASSWORD_BYTES + 1))
    # 中文按字节计：23 个汉字 = 69 字节通过，25 个 = 75 字节拒绝
    assert hash_password("密" * 23)
    with pytest.raises(PasswordPolicyError):
        hash_password("密" * 25)


def test_hash_is_salted_and_verifiable():
    h1 = hash_password("sup3r-secret-pw")
    h2 = hash_password("sup3r-secret-pw")
    assert h1 != h2, "相同密码必须因随机 salt 产生不同哈希"
    assert verify_password("sup3r-secret-pw", h1)
    assert verify_password("sup3r-secret-pw", h2)
    assert not verify_password("sup3r-secret-pW", h1)


def test_verify_password_rejects_garbage_hash():
    assert not verify_password("x", "not-a-bcrypt-hash")
    assert not verify_password("x", "")
