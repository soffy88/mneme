"""C2 红线单测：生产环境不得放行 mock 万能码旁路（手机号 + 邮箱双通道）。

CRG 审查发现 verify_code/verify_email_code/_mock_bypass_allowed/_check_lockout/
_register_failure 虽有 HTTP 集成覆盖（test_auth.py 锁定期/复位），但"生产禁
旁路"这一条 C2 红线从未被直接断言过——只有 test_prod_safety_gate.py 测了启动
闸门 main._assert_prod_safety，测不到运行期 verify 路径。

本文件用 FakeRedis 隔离（不污染共享 Redis 键），在单测层面锁定：
- prod 即便 SMS_PROVIDER/EMAIL_PROVIDER 误配为 mock，123456 也绝不放行
- prod 下真实验证码路径仍可用
- 无存储验证码 → 拒绝；错误码计数；锁定立即拒绝
- 日志脱敏 _mask_phone/_mask_email
"""

from __future__ import annotations

import pytest

from services import auth_service
from services.auth_service import (
    MOCK_CODE,
    _check_lockout,
    _mask_email,
    _mask_phone,
    _mock_bypass_allowed,
    _register_failure,
    verify_code,
    verify_email_code,
)


class _FakeRedis:
    """最小 async redis 替身：仅实现 auth_service 用到的命令。"""

    def __init__(self) -> None:
        self._str: dict[str, str] = {}
        self._int: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        if key in self._str:
            return self._str[key]
        if key in self._int:
            return str(self._int[key])
        return None

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self._str[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._str.pop(k, None)
            self._int.pop(k, None)

    async def incr(self, key: str) -> int:
        self._int[key] = self._int.get(key, 0) + 1
        return self._int[key]

    async def expire(self, _key: str, _ttl: int) -> None:
        pass

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch):
    r = _FakeRedis()
    monkeypatch.setattr(auth_service, "_redis", lambda: r)
    return r


# ── _mock_bypass_allowed ──────────────────────────────────────────────────────


def test_mock_bypass_allowed_dev(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MNEME_ENV", "dev")
    assert _mock_bypass_allowed() is True


def test_mock_bypass_allowed_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MNEME_ENV", raising=False)
    assert _mock_bypass_allowed() is True


def test_mock_bypass_allowed_blocked_in_prod(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MNEME_ENV", "prod")
    assert _mock_bypass_allowed() is False


# ── verify_code：手机号通道 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_code_mock_bypass_in_dev(fake_redis):
    """dev + mock provider：无存储验证码，万能码 123456 也应放行（演示机制）。"""
    assert await verify_code("13900001111", MOCK_CODE) is True


@pytest.mark.asyncio
async def test_verify_code_mock_bypass_blocked_in_prod(monkeypatch, fake_redis):
    """C2 红线：prod 即便 SMS_PROVIDER 误配 mock，123456 也绝不放行。"""
    monkeypatch.setenv("MNEME_ENV", "prod")
    monkeypatch.setenv("SMS_PROVIDER", "mock")
    assert await verify_code("13900002222", MOCK_CODE) is False


@pytest.mark.asyncio
async def test_verify_code_real_code_still_works_in_prod(monkeypatch, fake_redis):
    """prod 下真实验证码（非万能码）仍正常校验放行——只堵旁路，不堵真通道。"""
    monkeypatch.setenv("MNEME_ENV", "prod")
    await fake_redis.setex("sms:code:13900003333", 300, "654321")
    assert await verify_code("13900003333", "654321") is True


@pytest.mark.asyncio
async def test_verify_code_consumes_on_success(fake_redis):
    await fake_redis.setex("sms:code:13900004444", 300, "654321")
    assert await verify_code("13900004444", "654321") is True
    assert await fake_redis.get("sms:code:13900004444") is None


@pytest.mark.asyncio
async def test_verify_code_no_stored_rejects(fake_redis):
    assert await verify_code("13900005555", "654321") is False


@pytest.mark.asyncio
async def test_verify_code_wrong_code_counts_attempt(fake_redis):
    await fake_redis.setex("sms:code:13900006666", 300, "654321")
    assert await verify_code("13900006666", "999999") is False
    assert await fake_redis.get("sms:attempt:13900006666") == "1"


@pytest.mark.asyncio
async def test_verify_code_lockout_rejects_immediately(fake_redis):
    await fake_redis.setex("sms:lock:13900007777", 900, "1")
    assert await verify_code("13900007777", MOCK_CODE) is False


@pytest.mark.asyncio
async def test_verify_code_lockout_after_max_failures(fake_redis):
    """连续输错达到上限 → 通道锁定，之后输对也拒绝。"""
    await fake_redis.setex("sms:code:13900008888", 300, "654321")
    for _ in range(auth_service.MAX_VERIFY_ATTEMPTS):
        assert await verify_code("13900008888", "999999") is False
    assert await fake_redis.get("sms:lock:13900008888") is not None
    assert await verify_code("13900008888", "654321") is False


# ── verify_email_code：邮箱通道 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_email_code_mock_bypass_in_dev(fake_redis):
    assert await verify_email_code("kid@example.com", MOCK_CODE) is True


@pytest.mark.asyncio
async def test_verify_email_code_mock_bypass_blocked_in_prod(monkeypatch, fake_redis):
    monkeypatch.setenv("MNEME_ENV", "prod")
    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    assert await verify_email_code("kid@example.com", MOCK_CODE) is False


@pytest.mark.asyncio
async def test_verify_email_code_real_code_in_prod(monkeypatch, fake_redis):
    monkeypatch.setenv("MNEME_ENV", "prod")
    await fake_redis.setex("email:code:kid@example.com", 300, "654321")
    assert await verify_email_code("kid@example.com", "654321") is True


@pytest.mark.asyncio
async def test_verify_email_code_lockout(fake_redis):
    await fake_redis.setex("email:lock:kid@example.com", 900, "1")
    assert await verify_email_code("kid@example.com", MOCK_CODE) is False


# ── 日志脱敏（PII）────────────────────────────────────────────────────────────


def test_mask_phone_valid():
    assert _mask_phone("13812341234") == "138****1234"


def test_mask_phone_invalid_returns_stars():
    assert _mask_phone("12345") == "***"


def test_mask_email_valid():
    assert _mask_email("student@example.com") == "s***@example.com"


def test_mask_email_no_domain_returns_stars():
    assert _mask_email("not-an-email") == "***"


# ── _check_lockout / _register_failure：锁定原语（供 verify 路径间接使用）───────


@pytest.mark.asyncio
async def test_check_lockout_false_when_unset(fake_redis):
    assert await _check_lockout(fake_redis, "sms:lock:13900009999") is False


@pytest.mark.asyncio
async def test_check_lockout_true_when_set(fake_redis):
    await fake_redis.setex("sms:lock:13900009999", 900, "1")
    assert await _check_lockout(fake_redis, "sms:lock:13900009999") is True


@pytest.mark.asyncio
async def test_register_failure_counts_attempts(fake_redis):
    await _register_failure(fake_redis, "sms:attempt:13900008888", "sms:lock:13900008888")
    assert await fake_redis.get("sms:attempt:13900008888") == "1"
    assert await fake_redis.get("sms:lock:13900008888") is None


@pytest.mark.asyncio
async def test_register_failure_locks_after_max_and_clears_counter(fake_redis):
    for _ in range(auth_service.MAX_VERIFY_ATTEMPTS):
        await _register_failure(fake_redis, "sms:attempt:13900008888", "sms:lock:13900008888")
    assert await fake_redis.get("sms:lock:13900008888") is not None
    assert await fake_redis.get("sms:attempt:13900008888") is None
