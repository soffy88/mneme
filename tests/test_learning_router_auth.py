"""回归：/v1/learning/* 的本人校验曾写成 `await _ensure_student_self(...)`，
而该函数是同步、返回 None —— 本人合法调用全部 TypeError → 500（2026-10-10 审计）。"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from services.main import app, get_current_user
from services.models import User, UserRole


@pytest.mark.parametrize("path", ["/v1/learning/plan/{sid}", "/v1/learning/today/{sid}"])
async def test_learning_self_access_does_not_500(bypass_auth, path):
    sid = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(path.format(sid=sid))
    assert r.status_code < 500, r.text


async def test_learning_other_student_forbidden():
    me = User(id=uuid.uuid4(), phone="19900000000", role=UserRole.student)
    app.dependency_overrides[get_current_user] = lambda: me
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/v1/learning/plan/{uuid.uuid4()}")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
