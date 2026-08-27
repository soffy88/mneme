"""Mneme API 装配入口：lifespan + CORS + 域路由挂载。

业务路由已按域拆到 ``services/routers/``（auth / cognitive / practice / …）。
``get_current_user`` 等鉴权依赖仍从此处 re-export，兼容
``from services.main import app, get_current_user`` 与 dependency_overrides。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from obase.db import SessionLocal
from obase.prior_provider import PriorProvider
from obase.provider_registry import ProviderRegistry

# 鉴权依赖 re-export（对象同一，dependency_overrides 仍生效）
from services.auth_deps import (  # noqa: F401
    _ensure_session_owner,
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.email import get_email_provider
from services.logging_config import configure_logging, logger
from services.seed import seed_bkt_priors
from services.sms import get_sms_provider


def _assert_prod_safety() -> None:
    """生产环境(MNEME_ENV=prod)安全闸门：默认 JWT 密钥 / 无真实验证通道 一律拒启动。"""
    from obase.config import settings as _s
    from services.production_config import ProductionConfigError, validate_production_config

    if os.environ.get("MNEME_ENV", "dev").lower() not in {"prod", "production"}:
        return
    env = dict(os.environ)
    env.setdefault("JWT_SECRET", _s.JWT_SECRET)
    # pytest's fail-closed db guard intentionally injects mneme_test for all
    # tests.  It is not a production deployment setting and must not mask the
    # real production DB validation in a launched process.
    if env.get("TEST_DATABASE_URL") == env.get("DATABASE_URL"):
        env.pop("DATABASE_URL", None)
        env.pop("MINIO_ACCESS_KEY", None)
        env.pop("MINIO_SECRET_KEY", None)
    else:
        env.setdefault("DATABASE_URL", _s.DATABASE_URL)
    try:
        validate_production_config(env)
    except ProductionConfigError as exc:
        message = str(exc)
        if "verification provider" in message:
            message += "；无真实验证通道（SMS_PROVIDER≠aliyun 且 EMAIL_PROVIDER≠smtp）"
        raise RuntimeError("❌ 生产环境安全校验失败，拒绝启动：" + message) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _assert_prod_safety()

    # 沙箱零绕过自检（与 docker-compose command 双保险）。
    if os.environ.get("MNEME_SKIP_SANDBOX_SELFCHECK", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        from obase.sandbox_selfcheck import check_or_die

        check_or_die()

    from services.kernel_selfcheck import check_kernel_contract

    _missing = check_kernel_contract()
    if _missing:
        logger.error(
            "⚠️ 3O 内核契约缺失（功能可能静默失效，检查内核仓分支是否为 feat/edu-audit-fixes）: %s",
            ", ".join(_missing),
        )

    from obase.config import settings
    from obase.error_tag_store import ensure_error_tag_table
    from obase.interaction_history import ensure_interaction_history_table
    from obase.persistence.pool import PgPool

    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = await PgPool.get_or_create(dsn=dsn)
    await ensure_error_tag_table(pool)
    await ensure_interaction_history_table(pool)

    async with SessionLocal() as session:
        await seed_bkt_priors(session)
        await session.commit()
        await PriorProvider.warm_up(session)

    from services.providers.setup import configure_llm_providers

    _llm_tag = configure_llm_providers()
    logger.info(f"LLM default provider: {_llm_tag}")

    from services.providers.aliyun_pronunciation import AliyunPronunciationCaller

    aliyun_key = settings.ALIYUN_ACCESS_KEY_ID
    aliyun_secret = settings.ALIYUN_ACCESS_KEY_SECRET
    if aliyun_key and aliyun_secret:
        ProviderRegistry.register(
            "pronunciation",
            "aliyun",
            AliyunPronunciationCaller(
                aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY
            ),
        )
        ProviderRegistry.register(
            "pronunciation",
            "default",
            AliyunPronunciationCaller(
                aliyun_key, aliyun_secret, settings.ALIYUN_NLS_APP_KEY
            ),
        )
    else:
        logger.warning("阿里云语音评测未配置，口语陪练功能将使用 mock 评分")

        class MockPronunciationCaller:
            async def __call__(self, *, audio_b64: str, reference_text: str, **kwargs):
                from oprim._mneme_speech_types import PronunciationResult

                return PronunciationResult(
                    overall_score=0.85,
                    fluency_score=0.80,
                    accuracy_score=0.90,
                    word_scores=[],
                )

        ProviderRegistry.register("pronunciation", "aliyun", MockPronunciationCaller())
        ProviderRegistry.register("pronunciation", "default", MockPronunciationCaller())

    class MockASRCaller:
        async def __call__(self, *, audio_b64: str, language: str = "zh", **kwargs):
            return "Yes, this is a mock transcription of the student response."

    class MockTTSCaller:
        async def __call__(self, *, text: str, language: str = "en", **kwargs):
            return "dGVzdF9hdWRpb19kYXRh"

    ProviderRegistry.register("asr", "default", MockASRCaller())
    ProviderRegistry.register("tts", "default", MockTTSCaller())

    import services.main as _self

    _self._sms_provider = get_sms_provider()
    logger.info(f"SMS provider: {type(_self._sms_provider).__name__}")
    _self._email_provider = get_email_provider()
    logger.info(f"Email provider: {type(_self._email_provider).__name__}")

    yield


_sms_provider = get_sms_provider()
_email_provider = get_email_provider()

app = FastAPI(title="Mneme API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def user_safe_exception_handler(request: Request, exc: Exception):
    """Never expose stack traces, SQL, credentials, or internal IDs to users."""

    from services.errors import user_safe_error_payload

    trace_id = getattr(request.state, "trace_id", None)
    logger.error("request_failed", error_type=type(exc).__name__, trace_id=trace_id)
    return JSONResponse(
        status_code=500,
        content=user_safe_error_payload(trace_id=trace_id),
        headers={"X-Trace-Id": trace_id} if trace_id else None,
    )


@app.middleware("http")
async def request_observability(request: Request, call_next):
    """Propagate a trace ID and collect aggregate latency/error metrics."""

    import time

    from services.observability import (
        accept_trace_id,
        monotonic_ms,
        record_request,
        route_template,
    )

    trace_id = accept_trace_id(request.headers.get("x-trace-id"))
    request.state.trace_id = trace_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record_request(
            request.method,
            route_template(request.scope, request.url.path),
            500,
            monotonic_ms(started),
        )
        raise
    response.headers["X-Trace-Id"] = trace_id
    record_request(
        request.method,
        route_template(request.scope, request.url.path),
        response.status_code,
        monotonic_ms(started),
    )
    return response

try:
    from services.mcp_router import router as _mcp_router

    app.include_router(_mcp_router)
except ImportError as _mcp_import_err:  # pragma: no cover
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "MCP 工具面未挂载（mneme-core 不可用）: %s", _mcp_import_err
    )

try:
    from services.chat_router import router as _chat_router

    app.include_router(_chat_router)
except ImportError as _chat_import_err:  # pragma: no cover
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "chat 工作区未挂载（mneme-agent 不可用）: %s", _chat_import_err
    )

from services.routers import register_domain_routers  # noqa: E402

register_domain_routers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://sxueji.com",
        "https://mneme.kanpan.co",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
        "http://localhost:3006",
        "http://localhost:3007",
        "http://localhost:3008",
        "http://localhost:3009",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
