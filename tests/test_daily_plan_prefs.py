"""
V.2 每日计划参数可见+可配置：daily_plan_prefs 读写 + 接入 build_daily_plan 算法。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.daily_plan_service import build_daily_plan
from services.main import app
from services.models import KCMastery, User, UserRole


def _fsrs_card(overdue_days: int) -> dict:
    """同 tests/test_daily_plan.py 的同名 helper：造一张过期 N 天的 FSRS 卡。"""
    due = datetime.now(timezone.utc) - timedelta(days=overdue_days)
    return {
        "due": due.isoformat(),
        "stability": 1.0,
        "difficulty": 5.0,
        "elapsed_days": 0,
        "scheduled_days": 1,
        "reps": 1,
        "lapses": 0,
    }


def _mastery_kwargs(**overrides) -> dict:
    """KCMastery 的 p_init/p_transit/p_guess/p_slip 是 NOT NULL，测试里统一给个
    占位值（不影响本文件测的 daily_plan_prefs 行为）。"""
    return {
        "p_init": 0.45,
        "p_transit": 0.35,
        "p_guess": 0.25,
        "p_slip": 0.08,
        **overrides,
    }


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """自访问正向测试统一绕过 IDOR 鉴权。"""


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
async def student(db):
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"186{str(sid)[:8]}",
            role=UserRole.student,
            name="Test4",
            grade="高二",
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_daily_plan_prefs_crud(client, student):
    """默认值 → 部分更新 → budget_minutes 显式清空回不限 → 非法值拒绝，全放一个
    test function 里（同 test_error_journal.py 踩过的 get_pg_pool 跨 event loop 坑，
    这里虽然不碰那个 pool，但保持一致风格，避免下次谁复制这个文件时又踩进去）。"""
    # 默认值
    resp = await client.get(f"/v1/users/{student}/daily-plan-prefs")
    assert resp.status_code == 200
    assert resp.json() == {
        "budget_minutes": None,
        "late_night_hour": 22,
        "late_night_minute": 30,
        "weak_max_items": 3,
        "new_max_items": 2,
    }

    # 部分更新：只改 budget_minutes 和 weak_max_items，其余保留默认
    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs",
        json={"budget_minutes": 45, "weak_max_items": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_minutes"] == 45
    assert data["weak_max_items"] == 1
    assert data["late_night_hour"] == 22  # 未传，保留默认

    # 显式传 null 清空回"不限"（exclude_unset 区分"未传"与"传了 null"的关键场景）
    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs", json={"budget_minutes": None}
    )
    assert resp.status_code == 200
    assert resp.json()["budget_minutes"] is None
    assert resp.json()["weak_max_items"] == 1  # 上一步设的值仍保留

    # 非法值拒绝
    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs", json={"late_night_hour": 25}
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs", json={"budget_minutes": -5}
    )
    assert resp.status_code == 422
    print("  daily-plan-prefs CRUD + 非法值拒绝 + null 清空语义 ✓")


@pytest.mark.asyncio
async def test_unknown_field_rejected_at_service_layer(student, db):
    """set_daily_plan_prefs 本身的白名单校验（HTTP 端点的 Pydantic model 已经把未知
    字段过滤掉了，这条走服务函数直接测，覆盖 _ALLOWED_KEYS 这一层防线本身）。"""
    from services.daily_plan_prefs_service import set_daily_plan_prefs

    result = await set_daily_plan_prefs(db, student, {"unknown_field": 1})
    assert "error" in result
    print("  set_daily_plan_prefs 服务层未知字段拒绝 ✓")


@pytest.mark.asyncio
async def test_weak_max_items_pref_drives_estimated_minutes(client, student, db):
    """weak_max_items 真的接入了算法，不是存了没用上：调成 1 后薄弱任务的
    estimated_minutes 应该按 1 个算，不是默认 3 个。"""
    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs", json={"weak_max_items": 1}
    )
    assert resp.status_code == 200

    now = datetime.now(timezone.utc)
    for i in range(4):
        db.add(
            KCMastery(
                student_id=student,
                knowledge_point=f"GDMATH-WEAK-{i}",
                p_mastery=0.3,
                fsrs_card_json=None,
                **_mastery_kwargs(),
            )
        )
    await db.commit()

    plan = await build_daily_plan(db, student, subject="math", now=now)
    weak_tasks = [t for t in plan["tasks"] if t["type"] == "weak_practice"]
    assert len(weak_tasks) == 1
    assert weak_tasks[0]["estimated_minutes"] == 1 * 15  # MINUTES_PER_WEAK_KU=15, cap=1
    print("  weak_max_items=1 → estimated_minutes 按 1 个算，确认真接入算法 ✓")


@pytest.mark.asyncio
async def test_budget_minutes_pref_used_when_request_param_absent(client, student, db):
    """请求不传 budget_minutes 时回退到持久化的 prefs 值；请求显式传参数仍能临时覆盖。"""
    resp = await client.post(
        f"/v1/users/{student}/daily-plan-prefs", json={"budget_minutes": 5}
    )
    assert resp.status_code == 200

    now = datetime.now(timezone.utc)
    for i in range(2):
        db.add(
            KCMastery(
                student_id=student,
                knowledge_point=f"GDMATH-DUE-{i}",
                p_mastery=0.9,
                fsrs_card_json=_fsrs_card(overdue_days=1),
                **_mastery_kwargs(),
            )
        )
    await db.commit()

    # 不传 budget_minutes → 回退到持久化的 5 分钟，裁剪掉 dropped_tasks
    plan = await build_daily_plan(db, student, subject="math", now=now)
    assert plan["budget_minutes"] == 5

    # 显式传 100 → 临时覆盖持久化的 5，不裁剪
    plan2 = await build_daily_plan(
        db, student, subject="math", now=now, budget_minutes=100
    )
    assert plan2["budget_minutes"] == 100
    print("  budget_minutes：请求未传回退持久化值，显式传参数临时覆盖 ✓")
