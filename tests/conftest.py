"""共享测试夹具。

`bypass_auth`：把 get_current_user 覆盖为"按请求里的 student_id 返回匹配用户"，
用于那些 IDOR 加固后需要鉴权、但只访问自己数据的正向测试。**opt-in**（不 autouse），
不影响断言 401/403 的鉴权负向测试。
"""
from __future__ import annotations

import uuid

import pytest
from starlette.requests import Request

from services.main import app, get_current_user
from services.models import User, UserRole


async def _auth_from_request(request: Request) -> User:
    """返回 id 与请求 student_id（路径或 body）一致的学生用户，过自访问校验。"""
    sid = request.path_params.get("student_id")
    if not sid:
        try:
            body = await request.json()
            if isinstance(body, dict):
                sid = body.get("student_id")
        except Exception:
            sid = None
    uid = uuid.UUID(str(sid)) if sid else uuid.uuid4()
    return User(id=uid, phone=f"test{str(uid.int)[:8]}", role=UserRole.student)


@pytest.fixture
def bypass_auth():
    app.dependency_overrides[get_current_user] = _auth_from_request
    yield
    app.dependency_overrides.pop(get_current_user, None)
