"""嫁接 2：错题优先重测队列 + 确定性小抄。

纯函数排序/拼装直测 + mneme_test 库上的队列/小抄/路由/FSRS 分工测试。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import KCMastery, QuestionRecord, User, UserRole, WrongQuestion
from services.wrongbook_review_service import (
    build_cheatsheet,
    build_priority_queue,
    rank_review_items,
    render_cheatsheet,
    schedule_after_answer,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _item(item_id, due=None, errors=1, last=None):
    return {
        "item_id": item_id,
        "fsrs_due": due,
        "error_count": errors,
        "last_wrong_at": last,
    }


def test_rank_due_items_first_by_due_asc():
    items = [
        _item("new-high-errors", due=None, errors=9),
        _item("due-late", due=NOW - timedelta(hours=1), errors=1),
        _item("due-early", due=NOW - timedelta(days=2), errors=1),
    ]
    out = [it["item_id"] for it in rank_review_items(items, now=NOW)]
    assert out == ["due-early", "due-late", "new-high-errors"]


def test_rank_rest_by_error_count_then_recency():
    items = [
        _item("few-old", due=None, errors=1, last=NOW - timedelta(days=10)),
        _item("many-old", due=None, errors=5, last=NOW - timedelta(days=10)),
        _item("few-recent", due=None, errors=1, last=NOW - timedelta(hours=1)),
        _item("many-recent", due=None, errors=5, last=NOW - timedelta(hours=1)),
        _item("no-record", due=None, errors=1, last=None),
    ]
    out = [it["item_id"] for it in rank_review_items(items, now=NOW)]
    assert out == ["many-recent", "many-old", "few-recent", "few-old", "no-record"]


def test_rank_does_not_mutate_input_order():
    items = [_item("a", due=None, errors=2), _item("b", due=NOW - timedelta(days=1), errors=1)]
    rank_review_items(items, now=NOW)
    assert [it["item_id"] for it in items] == ["a", "b"]


def test_rank_future_due_is_not_due():
    items = [_item("future", due=NOW + timedelta(days=1), errors=1), _item("new", due=None, errors=3)]
    out = [it["item_id"] for it in rank_review_items(items, now=NOW)]
    assert out == ["new", "future"]


def test_render_cheatsheet_missing_sections_stay_blank():
    md = render_cheatsheet(
        [
            {
                "kc": "k1",
                "ku_name": None,
                "ku_description": None,
                "open_items": [{"question_text": "1+1=?", "error_type": None, "review_count": 0}],
            }
        ]
    )
    assert "1+1=?" in md
    assert "（暂无）" in md  # 资料原文缺项留空
    assert "（暂无小结）" in md  # 仓内无小结存储，不现编
    assert "（暂无记录）" in md  # 仓内无困惑点存储，不现编


def test_render_cheatsheet_empty_has_no_invented_content():
    md = render_cheatsheet([])
    assert "（暂无未关闭错题）" in md
    assert "小结" not in md.replace("（暂无未关闭错题）", "")


def test_render_cheatsheet_uses_material_text_verbatim():
    md = render_cheatsheet(
        [
            {
                "kc": "k1",
                "ku_name": "勾股定理",
                "ku_description": "直角三角形两直角边的平方和等于斜边的平方。",
                "open_items": [],
            }
        ]
    )
    assert "勾股定理" in md
    assert "直角三角形两直角边的平方和等于斜边的平方。" in md


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def student():
    a = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"177{str(a.int)[:8]}", role=UserRole.student, grade="初二"))
        await db.commit()
    yield a
    from services.purge_service import _STUDENT_TABLES, _table_exists

    async with SessionLocal() as db:
        for table, col in _STUDENT_TABLES:
            if await _table_exists(db, table):
                await db.execute(text(f"DELETE FROM {table} WHERE {col}::text = :i"), {"i": str(a)})
        await db.execute(text("DELETE FROM users WHERE id::text = :i"), {"i": str(a)})
        await db.commit()


async def _add_wq(student_id, qtext, *, due=None, kc=None, review_count=0):
    wq_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(
            WrongQuestion(
                id=wq_id,
                student_id=student_id,
                subject="math",
                question_text=qtext,
                correct_answer="7",
                knowledge_points={kc: "x"} if kc else None,
                fsrs_due=due,
                review_count=review_count,
            )
        )
        await db.commit()
    return wq_id


async def _add_wrong_record(student_id, wq_id):
    async with SessionLocal() as db:
        db.add(
            QuestionRecord(
                student_id=student_id,
                source="review",
                question_text="q",
                is_correct=False,
                wrong_question_id=wq_id,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_priority_queue_order_due_then_errors(student):
    a = student
    due_id = await _add_wq(a, "到期题", due=NOW - timedelta(days=1))
    many_id = await _add_wq(a, "错多次题", due=None)
    few_id = await _add_wq(a, "错一次题", due=None)
    for _ in range(3):
        await _add_wrong_record(a, many_id)
    await _add_wrong_record(a, few_id)
    async with SessionLocal() as db:
        out = await build_priority_queue(db, a, now=NOW)
    ids = [it["item_id"] for it in out["items"]]
    assert ids == [str(due_id), str(many_id), str(few_id)]
    assert out["total_open"] == 3
    by_id = {it["item_id"]: it for it in out["items"]}
    assert by_id[str(many_id)]["error_count"] == 3
    assert by_id[str(few_id)]["error_count"] == 1
    assert by_id[str(due_id)]["error_count"] == 1  # 本行即至少一次答错


@pytest.mark.asyncio
async def test_priority_queue_excludes_graduated(student):
    a = student
    open_id = await _add_wq(a, "未毕业题", due=None)
    grad_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(
            WrongQuestion(
                id=grad_id,
                student_id=a,
                subject="math",
                question_text="已毕业题",
                correct_answer="7",
                graduated_at=NOW,
            )
        )
        await db.commit()
    async with SessionLocal() as db:
        out = await build_priority_queue(db, a, now=NOW)
    ids = [it["item_id"] for it in out["items"]]
    assert ids == [str(open_id)]


@pytest.mark.asyncio
async def test_cheatsheet_groups_by_kc_and_leaves_blanks(student):
    a = student
    await _add_wq(a, "KC 题 1", kc="kc-blank")
    async with SessionLocal() as db:
        out = await build_cheatsheet(db, a)
    assert out["open_count"] == 1
    assert "KC 题 1" in out["markdown"]
    assert "（暂无小结）" in out["markdown"]
    assert "（暂无记录）" in out["markdown"]


@pytest.mark.asyncio
async def test_fsrs_schedule_does_not_write_mastery(student):
    """FSRS 只排期：schedule_after_answer 只动 fsrs_*/review_* 列，不写 KCMastery。"""
    a = student
    wq_id = await _add_wq(a, "排期题", due=None, kc="kc-fsrs-sep")
    async with SessionLocal() as db:
        wq = await db.get(WrongQuestion, wq_id)
        sched = schedule_after_answer(wq, is_correct=False, struggled=False, now=NOW)
        await db.commit()
        assert sched["next_due"]
        rows = (
            await db.execute(select(KCMastery).where(KCMastery.student_id == a))
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_priority_and_cheatsheet_routes(student):
    a = student
    await _add_wq(a, "路由题", due=NOW - timedelta(hours=2))
    async with _client() as c:
        r = await c.get("/v1/review/priority", headers=_h(a))
        assert r.status_code == 200, r.text
        assert r.json()["total_open"] == 1
        r2 = await c.get("/v1/review/cheatsheet", headers=_h(a))
        assert r2.status_code == 200, r2.text
        assert "路由题" in r2.json()["markdown"]
        r3 = await c.get("/v1/review/priority", headers=_h(uuid.uuid4()))
        assert r3.status_code in (401, 403) or r3.json()["total_open"] == 0
