"""/mcp HTTP 端点鉴权（W2b：/mcp 随 studio 公网暴露后必须每用户鉴权）。

验证三条：
- 无 token → 401（不再"内部可信免鉴权"）。
- 登录用户 A 拿他人 student_id=B 调 **写工具** → 403（_ensure_student_self，仅本人写认知数据）。
- 登录用户 A 拿他人 student_id=B 调 **读工具** → 403（_ensure_student_access，本人或绑定家长）。

tool_* 纯逻辑函数不受影响（其它 test_mcp_* 直调，不走 HTTP），此处只测 HTTP 鉴权闸门。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from services.main import app, get_current_user
from services.models import User, UserRole

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()  # 他人


def _as_user_a() -> User:
    return User(id=USER_A, phone="testA000", role=UserRole.student)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def login_as_a():
    app.dependency_overrides[get_current_user] = _as_user_a
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_no_token_401(client):
    """无 token：读工具和写工具都 401。"""
    r_read = await client.post(
        "/mcp/NextObjective",
        json={"student_id": str(USER_A), "kc_ids": ["renjiao-math-g10-a-ku004"]},
    )
    assert r_read.status_code == 401, r_read.text
    r_write = await client.post(
        "/mcp/RequestQuestion",
        json={"student_id": str(USER_A), "kc_id": "renjiao-math-g10-a-ku004"},
    )
    assert r_write.status_code == 401, r_write.text


@pytest.mark.asyncio
async def test_write_tool_other_student_403(client, login_as_a):
    """登录 A，写工具带他人 student_id=B → 403（仅本人写认知数据）。"""
    r = await client.post(
        "/mcp/RequestQuestion",
        json={"student_id": str(USER_B), "kc_id": "renjiao-math-g10-a-ku004"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_submit_answer_other_student_403(client, login_as_a):
    """SubmitAnswer 带他人 student_id=B → 403，且不被 500 兜底吞掉。"""
    r = await client.post(
        "/mcp/SubmitAnswer",
        json={"student_id": str(USER_B), "question_id": "q1", "answer": "a"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_read_tool_other_student_403(client, login_as_a):
    """登录 A，读工具带他人 student_id=B（无家长绑定）→ 403。"""
    r = await client.post(
        "/mcp/CheckMastery",
        json={"student_id": str(USER_B), "kc_id": "renjiao-math-g10-a-ku004"},
    )
    assert r.status_code == 403, r.text
