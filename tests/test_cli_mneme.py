"""W5 Part C：cli/mneme_cli.py 测试。

两层：① 用 httpx.MockTransport（httpx 自带，不引新依赖）对 MnemeClient 做纯逻辑
单测——每个子命令真的往正确的 /v1/auth/* 或 /mcp/* 路径发正确的 payload，不
碰真实网络/DB。② 两条真实端到端测试，直接打进程内 isolated ASGI app，证明红线成立：
CLI 跟人类用户走同一套 HTTP 面 + JWT 鉴权 + guard，跨学生访问一样被 403 拦下。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cli.mneme_cli import MnemeClient
from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import User, UserRole


def _mock_client(handler) -> MnemeClient:
    transport = httpx.MockTransport(handler)
    client = MnemeClient(base_url="http://mock", token="fake-token")

    def _patched(method, path, **kwargs):
        with httpx.Client(
            base_url=client.base_url, transport=transport, timeout=20.0
        ) as c:
            resp = c.request(method, path, headers=client._headers(), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    client._request = _patched  # type: ignore[method-assign]
    return client


def test_whoami_calls_get_auth_me():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "u1", "role": "student"})

    client = _mock_client(handler)
    result = client.whoami()

    assert seen["method"] == "GET"
    assert seen["path"] == "/v1/auth/me"
    assert seen["auth"] == "Bearer fake-token"
    assert result == {"id": "u1", "role": "student"}


def test_mcp_submit_answer_hits_correct_endpoint_with_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"is_correct": True})

    client = _mock_client(handler)
    result = client.mcp(
        "SubmitAnswer",
        {
            "student_id": "sid-1",
            "question_id": "q-1",
            "answer": "42",
            "time_spent_seconds": 30,
        },
    )

    assert seen["path"] == "/mcp/SubmitAnswer"
    assert seen["body"]["answer"] == "42"
    assert seen["body"]["time_spent_seconds"] == 30
    assert result == {"is_correct": True}


def test_mcp_bind_partner_channel_hits_correct_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"bound": True})

    client = _mock_client(handler)
    client.mcp(
        "BindPartnerChannel",
        {"student_id": "sid-1", "channel": "wecom", "target": "https://x.invalid"},
    )

    assert seen["path"] == "/mcp/BindPartnerChannel"
    assert seen["body"]["channel"] == "wecom"


def test_request_raises_runtime_error_on_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="无权访问该学生数据")

    client = _mock_client(handler)
    with pytest.raises(RuntimeError, match="403"):
        client.mcp("GetReviewQueue", {"student_id": "sid-1", "kc_ids": []})


def test_build_parser_wires_submit_answer_arguments():
    from cli.mneme_cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "submit-answer",
            "--student-id",
            "sid-1",
            "--question-id",
            "q-1",
            "--answer",
            "42",
            "--time-spent",
            "15",
        ]
    )
    assert args.student_id == "sid-1"
    assert args.question_id == "q-1"
    assert args.answer == "42"
    assert args.time_spent == 15
    assert args.func.__name__ == "cmd_submit_answer"


# ── 真实端到端：进程内 isolated ASGI app，不访问宿主/production ─────────────


class _SyncASGITransport(httpx.BaseTransport):
    """Bridge the sync CLI client to an in-process isolated ASGI app."""

    def __init__(self, application):
        self.application = application

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.application),
                base_url="http://isolated-test-server",
            ) as client:
                response = await client.request(
                    request.method,
                    request.url,
                    headers=request.headers,
                    content=request.content,
                )
                body = await response.aread()
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=body,
                    request=request,
                )

        result: list[httpx.Response] = []
        errors: list[BaseException] = []

        def run_in_isolated_loop() -> None:
            try:
                result.append(asyncio.run(send()))
            except BaseException as exc:  # pragma: no cover - bridge failure path
                errors.append(exc)

        thread = threading.Thread(target=run_in_isolated_loop)
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return result[0]


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
async def two_students(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    db.add(User(id=a, role=UserRole.student, name="CLI测试A", created_at=now))
    db.add(User(id=b, role=UserRole.student, name="CLI测试B", created_at=now))
    await db.commit()

    yield {"a": a, "b": b}

    await db.execute(delete(User).where(User.id.in_([a, b])))
    await db.commit()


def _isolated_client(token: str) -> MnemeClient:
    return MnemeClient(
        base_url="http://isolated-test-server",
        token=token,
        transport=_SyncASGITransport(app),
    )


@pytest.mark.asyncio
async def test_cli_whoami_against_real_running_server(two_students):
    """CLI 打真实跑着的 api（回环），whoami 拿到真实学生身份——证明 CLI 走的是
    真实 HTTP 面，不是套壳直连 DB。"""
    token = create_access_token({"sub": str(two_students["a"]), "role": "student"})
    client = _isolated_client(token)
    who = client.whoami()
    assert who["id"] == str(two_students["a"])


@pytest.mark.asyncio
async def test_cli_cannot_bypass_guard_cross_student_review_queue(two_students):
    """红线验证：CLI 用学生 A 的 token 查学生 B 的复习队列——真实服务器的
    _ensure_student_access guard 一样把它拦下来（403），证明 CLI 没有绕过任何
    既有护栏（走的是同一套 /mcp/* + JWT + guard）。"""
    token = create_access_token({"sub": str(two_students["a"]), "role": "student"})
    client = _isolated_client(token)

    with pytest.raises(RuntimeError, match="403"):
        client.mcp(
            "GetReviewQueue",
            {"student_id": str(two_students["b"]), "kc_ids": ["GDMATH-SET-01"]},
        )
