"""services/memory — S3 三层 Agent Memory 四模式（audit/dedup/merge/update）。

真 DB 写入（agent.* schema，migration e6f7a8b9c0d1）；单 session 不 commit，退出回滚，
不污染库（对照 test_gate_store.py 同一惯例）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from obase.db import SessionLocal
from services.memory import audit, dedup, merge, update


async def _insert_episodic(db, *, student_id, session_id, kind, content, created_at):
    return (
        await db.execute(
            text(
                "INSERT INTO agent.episodic_memory "
                "(student_id, session_id, kind, content, created_at) "
                "VALUES (CAST(:sid AS uuid), :session, :kind, CAST(:content AS jsonb), "
                ":created_at) RETURNING id"
            ),
            {
                "sid": str(student_id),
                "session": session_id,
                "kind": kind,
                "content": json.dumps(content),
                "created_at": created_at,
            },
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_audit_counts_empty_student():
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        report = await audit(db, sid)
        assert report["counts"] == {
            "working_memory": 0,
            "episodic_memory": 0,
            "semantic_memory": 0,
        }
        assert report["duplicate_groups"] == 0
        assert report["duplicate_rows"] == 0


@pytest.mark.asyncio
async def test_audit_reports_duplicates_without_deleting():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now,
        )
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now + timedelta(seconds=1),
        )
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "2"},
            created_at=now,
        )

        report = await audit(db, sid)
        assert report["counts"]["episodic_memory"] == 3
        assert report["duplicate_groups"] == 1
        assert report["duplicate_rows"] == 1  # 一组 2 条重复 → 多余 1 条

        # audit 只读：三条都还在
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM agent.episodic_memory "
                    "WHERE student_id = CAST(:sid AS uuid)"
                ),
                {"sid": str(sid)},
            )
        ).scalar_one()
        assert n == 3


@pytest.mark.asyncio
async def test_dedup_dry_run_does_not_delete():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        id1 = await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now,
        )
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now + timedelta(seconds=1),
        )

        result = await dedup(db, sid, dry_run=True)
        assert result["dry_run"] is True
        assert result["deleted_ids"] == []
        assert len(result["would_delete_ids"]) == 1
        assert (
            str(id1) not in result["would_delete_ids"]
        )  # 最早一条被保留、不进删除列表

        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM agent.episodic_memory "
                    "WHERE student_id = CAST(:sid AS uuid)"
                ),
                {"sid": str(sid)},
            )
        ).scalar_one()
        assert n == 2  # dry_run 未删


@pytest.mark.asyncio
async def test_dedup_keeps_earliest_deletes_rest():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    id1 = None
    async with SessionLocal() as db:
        id1 = await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now,
        )
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now + timedelta(seconds=1),
        )
        await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"q": "1"},
            created_at=now + timedelta(seconds=2),
        )

        result = await dedup(db, sid, dry_run=False)
        assert len(result["deleted_ids"]) == 2

        remaining = (
            (
                await db.execute(
                    text(
                        "SELECT id FROM agent.episodic_memory "
                        "WHERE student_id = CAST(:sid AS uuid)"
                    ),
                    {"sid": str(sid)},
                )
            )
            .scalars()
            .all()
        )
        assert remaining == [id1]  # 只留最早那条


@pytest.mark.asyncio
async def test_merge_creates_and_accumulates_semantic():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        id1 = await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"note": "a"},
            created_at=now,
        )
        id2 = await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"note": "b"},
            created_at=now,
        )

        r1 = await merge(db, sid, topic="algebra", episodic_ids=[id1])
        assert r1["matched_count"] == 1
        assert r1["total_items"] == 1

        # 追加合并第二条：累积而非覆盖
        r2 = await merge(db, sid, topic="algebra", episodic_ids=[id2])
        assert r2["matched_count"] == 1
        assert r2["total_items"] == 2

        row = (
            (
                await db.execute(
                    text(
                        "SELECT content, merged_from FROM agent.semantic_memory "
                        "WHERE student_id = CAST(:sid AS uuid) AND topic = 'algebra'"
                    ),
                    {"sid": str(sid)},
                )
            )
            .mappings()
            .first()
        )
        assert len(row["content"]["items"]) == 2
        assert set(row["merged_from"]) == {str(id1), str(id2)}


@pytest.mark.asyncio
async def test_merge_is_idempotent_on_same_episodic_id():
    sid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        id1 = await _insert_episodic(
            db,
            student_id=sid,
            session_id="s1",
            kind="tutor_turn",
            content={"note": "a"},
            created_at=now,
        )
        await merge(db, sid, topic="algebra", episodic_ids=[id1])
        r2 = await merge(db, sid, topic="algebra", episodic_ids=[id1])  # 重复传同一 id

        assert r2["matched_count"] == 0
        assert r2["skipped_already_merged"] == 1
        assert r2["total_items"] == 1  # 没有重复入 items


@pytest.mark.asyncio
async def test_update_overwrites_content():
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        await update(db, sid, topic="algebra", content={"summary": "v1"})
        result = await update(db, sid, topic="algebra", content={"summary": "v2"})
        assert result == {"topic": "algebra", "updated": True}

        row = (
            (
                await db.execute(
                    text(
                        "SELECT content FROM agent.semantic_memory "
                        "WHERE student_id = CAST(:sid AS uuid) AND topic = 'algebra'"
                    ),
                    {"sid": str(sid)},
                )
            )
            .mappings()
            .first()
        )
        assert row["content"] == {"summary": "v2"}
