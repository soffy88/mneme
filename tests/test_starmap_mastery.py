"""Word Atlas 部署第 2 步：GET/POST /v1/starmap/mastery 回归测试。

只写测试库 mneme_test（conftest/db_guard 钉死），只读当前登录学生本人的
kc_mastery 行。覆盖：
1. 未登录 → 401（GET 与 POST 均如此，仓内 get_current_user 既有约定）。
2. 学生隔离：A 的请求看不到 B 的行（同 KU 上 A/B 各一行时只返回 A 的值；
   仅 B 有行的 KU 对 A 返回未学；无范围时只返回 A 自己的全部行）。
3. 状态映射：p>=0.7→掌握；稳定度>=21 天→掌握；两值不一致时两值分开返回
   且 mastery_basis 标明点亮侧（解读以 BKT 为准）；有行未达标→学习中；
   无行→未学。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from obase.db import SessionLocal
from services.main import app, get_current_user
from services.models import KCMastery, User, UserRole

PREFIX = "starmap-step2-test-"


def _ku(name: str) -> str:
    return PREFIX + name


def _mastery_row(student_id, kp, p_mastery, stability):
    card = None if stability is None else {"stability": stability, "state": 1}
    return KCMastery(
        student_id=student_id,
        knowledge_point=kp,
        p_mastery=p_mastery,
        p_init=0.1,
        p_transit=0.1,
        p_guess=0.2,
        p_slip=0.1,
        fsrs_card_json=card,
        n_attempts=1,
    )


@pytest.fixture
async def two_students():
    """在 mneme_test 种两个学生 + 各自掌握行；测完清净（只清自己种的 id）。"""
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    ku_both = _ku("both")
    ku_b_only = _ku("b-only")
    async with SessionLocal() as db:
        db.add(User(id=student_a, role=UserRole.student))
        db.add(User(id=student_b, role=UserRole.student))
        await db.flush()
        # 同一 KU：A 已掌握（BKT 0.8），B 未达标（BKT 0.2）——隔离后 A 只能看到 0.8。
        db.add(_mastery_row(student_a, ku_both, 0.8, None))
        db.add(_mastery_row(student_b, ku_both, 0.2, None))
        # 仅 B 有行的 KU。
        db.add(_mastery_row(student_b, ku_b_only, 0.9, 30.0))
        await db.commit()
    yield {"a": student_a, "b": student_b, "both": ku_both, "b_only": ku_b_only}
    async with SessionLocal() as db:
        await db.execute(
            delete(KCMastery).where(KCMastery.knowledge_point.like(PREFIX + "%"))
        )
        await db.execute(
            delete(User).where(User.id.in_([student_a, student_b]))
        )
        await db.commit()


def _as(user_id):
    me = User(id=user_id, phone=None, role=UserRole.student)
    app.dependency_overrides[get_current_user] = lambda: me


@pytest.fixture
def _clear_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def test_starmap_mastery_unauthenticated_get_and_post(_clear_override):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/starmap/mastery")
        assert r.status_code == 401, r.text
        r = await c.post("/v1/starmap/mastery", json={"ku_ids": [_ku("x")]})
        assert r.status_code == 401, r.text


async def test_starmap_mastery_isolation(two_students, _clear_override):
    _as(two_students["a"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # POST 范围：同 KU 只见 A 的 0.8（掌握），仅 B 的 KU 对 A 是未学。
        r = await c.post(
            "/v1/starmap/mastery",
            json={"ku_ids": [two_students["both"], two_students["b_only"]]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["student_id"] == str(two_students["a"])
        assert str(two_students["b"]) not in r.text
        items = {it["ku_id"]: it for it in body["items"]}
        both = items[two_students["both"]]
        assert both["bkt_p_mastery"] == 0.8
        assert both["status"] == "掌握"
        assert both["mastery_basis"] == "bkt"
        b_only = items[two_students["b_only"]]
        assert b_only["bkt_p_mastery"] is None
        assert b_only["fsrs_stability_days"] is None
        assert b_only["status"] == "未学"
        # GET 无范围：只返回 A 自己的行，不含 B 的行、不含仅 B 的 KU。
        r = await c.get("/v1/starmap/mastery")
        assert r.status_code == 200, r.text
        items = {it["ku_id"]: it for it in r.json()["items"]}
        assert two_students["both"] in items
        assert two_students["b_only"] not in items
        assert all(it["bkt_p_mastery"] == 0.8 for it in items.values())


async def test_starmap_mastery_status_mapping(_clear_override):
    student = uuid.uuid4()
    ku_bkt = _ku("bkt-edge")  # p == 0.7 恰好达标 → 掌握
    ku_fsrs = _ku("fsrs-only")  # BKT 0.5 未达标、稳定度 21 达标 → 掌握（basis fsrs）
    ku_fsrs_below = _ku("fsrs-below")  # BKT 0.69、稳定度 20.9 → 学习中
    ku_learning = _ku("learning")  # 有行、两项均未达标 → 学习中
    ku_none = _ku("no-row")  # 无行 → 未学
    async with SessionLocal() as db:
        db.add(User(id=student, role=UserRole.student))
        await db.flush()
        db.add(_mastery_row(student, ku_bkt, 0.7, None))
        db.add(_mastery_row(student, ku_fsrs, 0.5, 21.0))
        db.add(_mastery_row(student, ku_fsrs_below, 0.69, 20.9))
        db.add(_mastery_row(student, ku_learning, 0.3, 5.0))
        await db.commit()
    try:
        _as(student)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/v1/starmap/mastery",
                json={
                    "ku_ids": [ku_bkt, ku_fsrs, ku_fsrs_below, ku_learning, ku_none]
                },
            )
            assert r.status_code == 200, r.text
            items = {it["ku_id"]: it for it in r.json()["items"]}
            assert items[ku_bkt]["status"] == "掌握"
            assert items[ku_bkt]["mastery_basis"] == "bkt"
            # 两值不一致：两值分开返回，点亮侧标为 fsrs（解读以 BKT 为准）。
            assert items[ku_fsrs]["status"] == "掌握"
            assert items[ku_fsrs]["bkt_p_mastery"] == 0.5
            assert items[ku_fsrs]["fsrs_stability_days"] == 21.0
            assert items[ku_fsrs]["mastery_basis"] == "fsrs"
            assert items[ku_fsrs_below]["status"] == "学习中"
            assert items[ku_fsrs_below]["mastery_basis"] is None
            assert items[ku_learning]["status"] == "学习中"
            assert items[ku_none]["status"] == "未学"
            assert items[ku_none]["bkt_p_mastery"] is None
            assert items[ku_none]["fsrs_stability_days"] is None
            counts = r.json()["counts"]
            assert counts == {"掌握": 2, "学习中": 2, "未学": 1}
            # GET 重复 ku_id 参数同样走请求范围。
            r = await c.get(
                "/v1/starmap/mastery",
                params=[("ku_id", ku_bkt), ("ku_id", ku_none)],
            )
            assert r.status_code == 200, r.text
            assert [it["ku_id"] for it in r.json()["items"]] == [ku_bkt, ku_none]
    finally:
        async with SessionLocal() as db:
            await db.execute(
                delete(KCMastery).where(
                    KCMastery.knowledge_point.like(PREFIX + "%")
                )
            )
            await db.execute(delete(User).where(User.id == student))
            await db.commit()
