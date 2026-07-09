"""P0 IDOR 鉴权加固测试。

覆盖：
① 匿名调核心写接口（interaction / practice/submit / socratic/start）→ 401
② 学生 A 的 token 提交 student_id=B → 403
③ 绑定家长可读孩子数据，但不可替孩子写 interaction → 403
④ GET /v1/auth/me 返回学生 invite_code（供家长绑定）
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import ParentStudent, User, UserRole

KC_ID = "GDMATH-CONIC-01"


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


# ── fixtures ─────────────────────────────────────────────────────────────────


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
async def actors(db):
    """学生A + 学生B + 绑定A的家长P。"""
    a, b, p = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.add(
        User(
            id=a,
            phone=f"191{str(a.int)[:8]}",
            role=UserRole.student,
            name="学生A",
            grade="高一",
            invite_code=uuid.uuid4().hex[:6].upper(),
        )
    )
    db.add(
        User(
            id=b,
            phone=f"192{str(b.int)[:8]}",
            role=UserRole.student,
            name="学生B",
            grade="高一",
        )
    )
    db.add(User(id=p, phone=f"193{str(p.int)[:8]}", role=UserRole.parent, name="家长P"))
    await db.flush()
    db.add(ParentStudent(parent_id=p, student_id=a))
    await db.commit()
    yield {"a": a, "b": b, "p": p}
    await db.execute(delete(ParentStudent).where(ParentStudent.parent_id == p))
    await db.execute(delete(User).where(User.id.in_([a, b, p])))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── ① 匿名 → 401 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_interaction_401(client):
    r = await client.post(
        "/v1/interaction",
        json={
            "student_id": str(uuid.uuid4()),
            "ku_id": KC_ID,
            "is_correct": True,
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_practice_submit_401(client):
    r = await client.post(
        "/v1/practice/submit",
        json={
            "question_id": str(uuid.uuid4()),
            "student_id": str(uuid.uuid4()),
            "student_answer": "4",
            "ku_id": "ku-x",
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_socratic_start_401(client):
    r = await client.post(
        "/v1/socratic/start",
        params={
            "question_id": str(uuid.uuid4()),
            "student_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_papers_upload_401(client):
    r = await client.post(
        f"/v1/papers/upload?student_id={uuid.uuid4()}",
        files={"file": ("t.jpg", b"x", "image/jpeg")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_daily_plan_401(client):
    r = await client.get(f"/v1/daily-plan/{uuid.uuid4()}")
    assert r.status_code == 401


# ── ② 学生A token 操作 student_id=B → 403 ────────────────────────────────────


@pytest.mark.asyncio
async def test_student_a_cannot_write_interaction_for_b(client, actors):
    r = await client.post(
        "/v1/interaction",
        json={
            "student_id": str(actors["b"]),
            "ku_id": KC_ID,
            "is_correct": True,
        },
        headers=_h(actors["a"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_a_cannot_practice_submit_for_b(client, actors):
    r = await client.post(
        "/v1/practice/submit",
        json={
            "question_id": str(uuid.uuid4()),
            "student_id": str(actors["b"]),
            "student_answer": "4",
            "ku_id": "ku-x",
        },
        headers=_h(actors["a"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_a_cannot_socratic_start_for_b(client, actors):
    r = await client.post(
        "/v1/socratic/start",
        params={
            "question_id": str(uuid.uuid4()),
            "student_id": str(actors["b"]),
        },
        headers=_h(actors["a"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_a_cannot_read_b_mastery(client, actors):
    r = await client.get(f"/v1/mastery/{actors['b']}", headers=_h(actors["a"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_a_cannot_read_b_papers(client, actors):
    r = await client.get(
        "/v1/papers", params={"student_id": str(actors["b"])}, headers=_h(actors["a"])
    )
    assert r.status_code == 403


# ── ③ 绑定家长：可读孩子数据，不可写 interaction ─────────────────────────────


@pytest.mark.asyncio
async def test_bound_parent_can_read_child_papers(client, actors):
    r = await client.get(
        "/v1/papers", params={"student_id": str(actors["a"])}, headers=_h(actors["p"])
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_bound_parent_can_read_child_mastery(client, actors):
    r = await client.get(f"/v1/mastery/{actors['a']}", headers=_h(actors["p"]))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_bound_parent_cannot_write_interaction(client, actors):
    r = await client.post(
        "/v1/interaction",
        json={
            "student_id": str(actors["a"]),
            "ku_id": KC_ID,
            "is_correct": True,
        },
        headers=_h(actors["p"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_bound_parent_cannot_read_other_student(client, actors):
    """家长绑定的是 A，读 B → 403。"""
    r = await client.get(f"/v1/mastery/{actors['b']}", headers=_h(actors["p"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_bound_parent_cannot_submit_quiz_for_child(client, actors):
    """上线体检修复：quiz/submit 是认知写入（回写BKT/FSRS），家长不可替孩子提交。
    _ensure_student_self 在任何 quiz 查询之前先拦截，随机 quiz_id 也应 403（不是404）。"""
    r = await client.post(
        f"/v1/quiz/{uuid.uuid4()}/submit",
        params={"student_id": str(actors["a"])},
        json={"answers": [], "time_spent_seconds": 60},
        headers=_h(actors["p"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_bound_parent_cannot_submit_gate_check_for_child(client, actors):
    """上线体检修复：mastery gate-check 提交会写 KCMastery.mastery_confirmed，
    属替孩子写掌握状态，家长不可代答 → 403。"""
    r = await client.post(
        f"/v1/mastery/gate-check/{actors['a']}/{KC_ID}",
        json={"student_answer": "42"},
        headers=_h(actors["p"]),
    )
    assert r.status_code == 403


# ── ④ /v1/auth/me 返回 invite_code ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_me_returns_invite_code(client, db, actors):
    student = await db.get(User, actors["a"])
    r = await client.get("/v1/auth/me", headers=_h(actors["a"]))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(actors["a"])
    assert body["name"] == "学生A"
    assert body["grade"] == "高一"
    assert body["invite_code"] == student.invite_code
    assert body["invite_code"]  # 非空，供家长绑定


# ── ⑤ bind-child：commit 后读 ORM 对象属性回归测试 ────────────────────────────
# 这条走的是 app 自己的 get_db()（真实 obase.db.SessionLocal，expire_on_commit=True
# 默认值），不是本文件 db 夹具那个专门设了 expire_on_commit=False 的测试 engine——
# 所以能测出"commit 后读对象属性触发 MissingGreenlet"这类坑，本文件其它测试测不出来。


@pytest.mark.asyncio
async def test_bind_child_unknown_invite_code_404(client, actors):
    r = await client.post(
        "/v1/auth/bind-child",
        params={"invite_code": "ZZZZZZ"},
        headers=_h(actors["p"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_bind_new_child_success_after_commit(client, db):
    """真实新增绑定路径（此前无绑定关系，触发 add+commit）：返回体读
    student_id/student_name 不应该因 commit 后隐式惰性刷新而 500。"""
    parent_id, student_id = uuid.uuid4(), uuid.uuid4()
    code = uuid.uuid4().hex[:6].upper()
    db.add(
        User(
            id=parent_id,
            phone=f"194{str(parent_id.int)[:8]}",
            role=UserRole.parent,
            name="家长Q",
        )
    )
    db.add(
        User(
            id=student_id,
            phone=f"195{str(student_id.int)[:8]}",
            role=UserRole.student,
            name="学生C",
            grade="高二",
            invite_code=code,
        )
    )
    await db.commit()
    try:
        r = await client.post(
            "/v1/auth/bind-child",
            params={"invite_code": code},
            headers=_h(parent_id),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["student_id"] == str(student_id)
        assert body["student_name"] == "学生C"
    finally:
        await db.execute(
            delete(ParentStudent).where(ParentStudent.parent_id == parent_id)
        )
        await db.execute(delete(User).where(User.id.in_([parent_id, student_id])))
        await db.commit()
