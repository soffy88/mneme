"""
X.7 补测试：_assert_prod_safety——生产环境启动安全闸门（JWT_SECRET/SMS_PROVIDER
校验）。此前零测试覆盖，httpx ASGITransport 不触发 FastAPI lifespan，
之前没人直接单测过这个函数；一旦条件判断写反，线上会带着可伪造token的默认
密钥/万能验证码启动而没有任何告警。纯函数，monkeypatch 隔离，不污染其它测试。
"""

from __future__ import annotations

from services.main import _assert_prod_safety


def test_non_prod_env_always_passes(monkeypatch):
    monkeypatch.delenv("MNEME_ENV", raising=False)
    _assert_prod_safety()  # 默认 dev，不应抛异常，即便密钥是默认值

    monkeypatch.setenv("MNEME_ENV", "dev")
    _assert_prod_safety()

    monkeypatch.setenv("MNEME_ENV", "demo")
    _assert_prod_safety()


def test_prod_with_default_jwt_secret_and_mock_sms_refuses_to_start(monkeypatch):
    from obase.config import settings

    monkeypatch.setenv("MNEME_ENV", "prod")
    monkeypatch.setattr(settings, "JWT_SECRET", "mneme-dev-secret-change-in-prod!")
    monkeypatch.delenv("SMS_PROVIDER", raising=False)

    try:
        _assert_prod_safety()
        assert False, "应该拒绝启动"
    except RuntimeError as e:
        assert "JWT_SECRET" in str(e)
        assert "SMS_PROVIDER" in str(e)
    print("  prod + 默认密钥 + mock短信 → 拒绝启动，两个问题都报出来 ✓")


def test_prod_with_real_secret_and_aliyun_sms_starts_cleanly(monkeypatch):
    from obase.config import settings

    monkeypatch.setenv("MNEME_ENV", "prod")
    monkeypatch.setattr(settings, "JWT_SECRET", "a-real-rotated-production-secret")
    monkeypatch.setenv("SMS_PROVIDER", "aliyun")

    _assert_prod_safety()  # 不应抛异常
    print("  prod + 真实密钥 + aliyun短信 → 正常放行 ✓")


def test_prod_with_only_one_problem_still_refuses(monkeypatch):
    """只改对了一半（换了密钥但还是mock短信）也不能放行——两个校验独立生效。"""
    from obase.config import settings

    monkeypatch.setenv("MNEME_ENV", "prod")
    monkeypatch.setattr(settings, "JWT_SECRET", "a-real-rotated-production-secret")
    monkeypatch.setenv("SMS_PROVIDER", "mock")

    try:
        _assert_prod_safety()
        assert False, "应该拒绝启动"
    except RuntimeError as e:
        assert "SMS_PROVIDER" in str(e)
        assert "JWT_SECRET" not in str(e)  # 密钥这项已经修好了，不该被误报
    print("  只修好一半仍拒绝启动，且不误报已修好的那项 ✓")
