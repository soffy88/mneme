"""共享测试夹具。

`bypass_auth`：把 get_current_user 覆盖为"按请求里的 student_id 返回匹配用户"，
用于那些 IDOR 加固后需要鉴权、但只访问自己数据的正向测试。**opt-in**（不 autouse），
不影响断言 401/403 的鉴权负向测试。

student_id 解析顺序：路径参数 → query 参数 → JSON body →
资源归属反查（session_id/mission_id/paper_id/question_id 等无 student_id 的路由，
按 DB 行的 student_id 回填，保证"资源归属校验"类鉴权也能以 owner 身份通过）。
"""

from __future__ import annotations

import uuid

import pytest
from starlette.requests import Request

from services.main import app, get_current_user
from services.models import User, UserRole


async def _owner_of_resource(path_params: dict) -> str | None:
    """按资源行反查归属学生（无 student_id 参数的路由用）。"""
    from obase.db import SessionLocal
    from sqlalchemy import select

    from services.models import DailyMission, Paper, SocraticSession, WrongQuestion

    lookups = [
        ("session_id", SocraticSession),
        ("mission_id", DailyMission),
        ("paper_id", Paper),
        ("question_id", WrongQuestion),
    ]
    for key, model in lookups:
        raw = path_params.get(key)
        if not raw:
            continue
        try:
            rid = uuid.UUID(str(raw))
        except ValueError:
            continue
        async with SessionLocal() as db:
            owner = (
                await db.execute(select(model.student_id).where(model.id == rid))
            ).scalar_one_or_none()
        if owner:
            return str(owner)
    return None


async def _auth_from_request(request: Request) -> User:
    """返回 id 与请求 student_id（路径/query/body/资源归属）一致的学生用户，过自访问校验。"""
    sid = request.path_params.get("student_id") or request.query_params.get(
        "student_id"
    )
    if not sid:
        try:
            body = await request.json()
            if isinstance(body, dict):
                sid = body.get("student_id")
        except Exception:
            sid = None
    if not sid:
        sid = await _owner_of_resource(request.path_params)
    uid = uuid.UUID(str(sid)) if sid else uuid.uuid4()
    return User(id=uid, phone=f"test{str(uid.int)[:8]}", role=UserRole.student)


@pytest.fixture
def bypass_auth():
    app.dependency_overrides[get_current_user] = _auth_from_request
    yield
    app.dependency_overrides.pop(get_current_user, None)
