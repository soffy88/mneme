"""Practice queue —— Studio /practice 的只读队列（FSRS 到期 KC + 本人错题，不含答案）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import KCMastery, User, UserRole, WrongQuestion
from services.practice_queue_service import practice_queue

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _mastery(sid: uuid.UUID, kc: str, due: datetime | None) -> KCMastery:
    return KCMastery(
        student_id=sid,
        knowledge_point=kc,
        p_mastery=0.6,
        p_init=0.2,
        p_transit=0.1,
        p_guess=0.2,
        p_slip=0.1,
        fsrs_card_json={"due": due.isoformat()} if due else None,
    )


@pytest.mark.asyncio
async def test_queue_orders_due_and_never_returns_answers():
    async with SessionLocal() as db:
        sid, other = uuid.uuid4(), uuid.uuid4()
        db.add(User(id=sid, phone=f"171{str(sid.int)[:8]}", role=UserRole.student))
        db.add(User(id=other, phone=f"172{str(other.int)[:8]}", role=UserRole.student))
        await db.flush()
        db.add_all(
            [
                _mastery(sid, "kc-old", NOW - timedelta(days=3)),
                _mastery(sid, "kc-new", NOW - timedelta(hours=2)),
                _mastery(sid, "kc-future", NOW + timedelta(days=2)),
                _mastery(sid, "kc-nocard", None),
                _mastery(other, "kc-old", NOW - timedelta(days=9)),
            ]
        )
        for _ in range(2):  # 同题错两次 → 去重计 2
            db.add(
                WrongQuestion(
                    student_id=sid,
                    question_text="解不等式 x+1>2",
                    correct_answer="x>1",
                    student_answer="x>3",
                    knowledge_points={"kc-old": 1.0},
                )
            )
        db.add(
            WrongQuestion(
                student_id=other,
                question_text="别人的错题",
                correct_answer="SECRET",
                knowledge_points={"kc-old": 1.0},
            )
        )
        await db.flush()

        q = await practice_queue(db, sid, now=NOW)
        assert [d["kc_id"] for d in q["due"]] == ["kc-old", "kc-new"]
        assert q["due_count"] == 2
        assert [u["kc_id"] for u in q["upcoming"]] == ["kc-future"]
        old = q["due"][0]
        assert old["wrong_count"] == 2
        assert old["sample_wrong_question"] == "解不等式 x+1>2"
        assert old["overdue_hours"] == 72.0
        assert len(q["wrong_questions"]) == 1
        wq = q["wrong_questions"][0]
        assert wq["wrong_count"] == 2 and wq["kc_due"] is True
        # 红线：答案字段与答案值都不出现在返回体
        blob = repr(q)
        assert "correct_answer" not in blob and "x>1" not in blob
        assert "SECRET" not in blob and "别人的错题" not in blob
        await db.rollback()


@pytest.fixture
async def two_students():
    a, b = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"173{str(a.int)[:8]}", role=UserRole.student))
        db.add(User(id=b, phone=f"174{str(b.int)[:8]}", role=UserRole.student))
        await db.commit()
    yield a, b
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.id.in_([a, b])))
        await db.commit()


@pytest.mark.asyncio
async def test_practice_queue_route_self_only(two_students):
    a, b = two_students

    def h(u: uuid.UUID) -> dict:
        return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(f"/v2/practice/queue/{a}", headers=h(a))
        assert ok.status_code == 200
        assert ok.json()["due"] == [] and ok.json()["wrong_questions"] == []
        assert (await c.get(f"/v2/practice/queue/{a}", headers=h(b))).status_code == 403
        assert (await c.get(f"/v2/practice/queue/{a}")).status_code == 401
