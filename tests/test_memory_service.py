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
from services.memory import (
    append_episode,
    audit,
    cleanup_expired_working_memory,
    dedup,
    merge,
    recall,
    update,
)


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


# —— C5 follow-ups：append_episode / recall / TTL 清理 / merge 接 LLM ——


@pytest.mark.asyncio
async def test_append_episode_creates_row_and_returns_id():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        result = await append_episode(
            db, sid, kind="tutor_turn", content={"note": "a"}, session_id="s1"
        )
        assert result["kind"] == "tutor_turn"
        assert result["id"]

        row = (
            (
                await db.execute(
                    text(
                        "SELECT kind, content, session_id FROM agent.episodic_memory "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": result["id"]},
                )
            )
            .mappings()
            .first()
        )
        assert row["kind"] == "tutor_turn"
        assert row["content"] == {"note": "a"}
        assert row["session_id"] == "s1"


@pytest.mark.asyncio
async def test_recall_by_topic_and_default_recent():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        await update(db, sid, topic="algebra", content={"summary": "s1"})
        await update(db, sid, topic="geometry", content={"summary": "s2"})

        by_topic = await recall(db, sid, topic="algebra")
        assert by_topic["memories"] == [
            {"topic": "algebra", "content": {"summary": "s1"}}
        ]

        recent = await recall(db, sid)
        assert {m["topic"] for m in recent["memories"]} == {"algebra", "geometry"}


@pytest.mark.asyncio
async def test_recall_unknown_topic_returns_empty():
    async with SessionLocal() as db:
        result = await recall(db, uuid.uuid4(), topic="no-such-topic")
        assert result["memories"] == []


@pytest.mark.asyncio
async def test_cleanup_expired_working_memory_deletes_only_expired():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        await db.execute(
            text(
                "INSERT INTO agent.working_memory "
                "(student_id, session_id, content, expires_at) "
                "VALUES (CAST(:sid AS uuid), 's1', CAST(:c AS jsonb), :expires)"
            ),
            {
                "sid": str(sid),
                "c": json.dumps({"expired": True}),
                "expires": now - timedelta(minutes=1),
            },
        )
        await db.execute(
            text(
                "INSERT INTO agent.working_memory "
                "(student_id, session_id, content, expires_at) "
                "VALUES (CAST(:sid AS uuid), 's1', CAST(:c AS jsonb), :expires)"
            ),
            {
                "sid": str(sid),
                "c": json.dumps({"expired": False}),
                "expires": now + timedelta(hours=1),
            },
        )

        result = await cleanup_expired_working_memory(db)
        assert result["deleted_count"] >= 1

        remaining = (
            (
                await db.execute(
                    text(
                        "SELECT content FROM agent.working_memory "
                        "WHERE student_id = CAST(:sid AS uuid)"
                    ),
                    {"sid": str(sid)},
                )
            )
            .mappings()
            .all()
        )
        assert [r["content"] for r in remaining] == [{"expired": False}]


@pytest.mark.asyncio
async def test_merge_without_llm_has_no_summary_field_backward_compatible():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        ep = await append_episode(db, sid, kind="tutor_turn", content={"note": "a"})
        result = await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep["id"])]
        )
        assert result["summary"] is None

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
        assert "summary" not in row["content"]


@pytest.mark.asyncio
async def test_merge_with_llm_generates_and_updates_summary():
    calls: list[str] = []

    async def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return f"摘要版本{len(calls)}"

    async with SessionLocal() as db:
        sid = uuid.uuid4()
        ep1 = await append_episode(
            db, sid, kind="tutor_turn", content={"note": "第一次"}
        )
        r1 = await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep1["id"])], llm=fake_llm
        )
        assert r1["summary"] == "摘要版本1"
        assert "（无）" in calls[0]  # 首次合并，无既有摘要

        ep2 = await append_episode(
            db, sid, kind="tutor_turn", content={"note": "第二次"}
        )
        r2 = await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep2["id"])], llm=fake_llm
        )
        assert r2["summary"] == "摘要版本2"
        assert "摘要版本1" in calls[1]  # 第二次合并，prompt 里带上一版摘要


@pytest.mark.asyncio
async def test_merge_with_llm_failure_does_not_block_merge():
    async def broken_llm(prompt: str) -> str:
        del prompt
        raise RuntimeError("network down")

    async with SessionLocal() as db:
        sid = uuid.uuid4()
        ep = await append_episode(db, sid, kind="tutor_turn", content={"note": "a"})
        result = await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep["id"])], llm=broken_llm
        )
        assert result["matched_count"] == 1  # 机械合并仍成功
        assert result["summary"] is None  # 只是没有摘要


@pytest.mark.asyncio
async def test_merge_with_llm_no_new_rows_skips_llm_call():
    calls: list[str] = []

    async def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "不该被调用"

    async with SessionLocal() as db:
        sid = uuid.uuid4()
        ep = await append_episode(db, sid, kind="tutor_turn", content={"note": "a"})
        await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep["id"])], llm=fake_llm
        )
        calls.clear()
        # 重复传同一个已合并过的 id：无新增行，不该再调 LLM
        result = await merge(
            db, sid, topic="algebra", episodic_ids=[uuid.UUID(ep["id"])], llm=fake_llm
        )
        assert calls == []
        assert result["summary"] == "不该被调用"  # 保留上一轮的摘要，未被清空
