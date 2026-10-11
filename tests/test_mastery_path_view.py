"""GetMasteryPath —— 学习者可见的掌握路径（mastery / current / locked）。

状态完全由既有内核 is_mastered（经 mastery_path omodul → map_summary）派生：
第一个未过门 KC 是唯一 current，之后的未过门 KC 全部 locked；已过门 = mastered。
用假 GetPath + 假 LearningProgress 隔离 DB，只测派生规则与只读性。
"""

from __future__ import annotations

import uuid

import pytest

import services.mcp_router as mr
from mneme_core.domain.oprim.models import (
    BktPosterior,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
    ReviewTask,
)

KCS = ["kc-a", "kc-b", "kc-c", "kc-d"]


def _progress(bkt: dict, qual: dict | None = None, review=None) -> LearningProgress:
    kps = [
        KnowledgePoint(id="kc-a", name="集合", type=KnowledgeType.PROCEDURE),
        KnowledgePoint(id="kc-b", name="函数概念", type=KnowledgeType.CONCEPT),
        KnowledgePoint(id="kc-c", name="不等式", type=KnowledgeType.PROCEDURE),
        KnowledgePoint(id="kc-d", name="三角", type=KnowledgeType.PROCEDURE),
    ]
    return LearningProgress(
        student_id="s",
        modules=[Module(id="path", name="path", order=0, knowledge_points=kps)],
        bkt=bkt,
        qualitative_mastery=qual or {},
        review_queue=review or [],
    )


@pytest.fixture
def fake_path(monkeypatch):
    holder: dict = {}

    async def _get_path(db, student_id, textbook_id=mr.DEFAULT_TEXTBOOK):
        return {"textbook_id": "tb", "kc_ids": holder.get("kcs", KCS)}

    async def _build(db, student_id, kc_ids):
        return holder["progress"]

    monkeypatch.setattr(mr, "tool_get_path", _get_path)
    monkeypatch.setattr(mr, "build_learning_progress", _build)
    return holder


@pytest.mark.asyncio
async def test_first_unmastered_is_current_rest_locked(fake_path):
    strong = BktPosterior(p_learned=0.99, sigma=0.01, n_obs=10)
    weak = BktPosterior(p_learned=0.4, sigma=0.2, n_obs=3)
    fake_path["progress"] = _progress(
        {"kc-a": strong, "kc-c": weak}, qual={"kc-b": True}
    )
    r = await mr.tool_get_mastery_path(None, uuid.uuid4(), now=1000.0)
    assert r["status"] == "completed"
    states = {n["kc_id"]: n["state"] for n in r["nodes"]}
    assert states == {
        "kc-a": "mastered",
        "kc-b": "mastered",  # 定性 KC 过门来自 qualitative_mastery（真 verifier），非 LLM 现场判
        "kc-c": "current",
        "kc-d": "locked",
    }
    assert r["current_kc_id"] == "kc-c"
    assert r["total_mastered"] == 2 and r["total_kps"] == 4
    assert [n["kc_id"] for n in r["nodes"]] == KCS  # 保持 GetPath 章节序


@pytest.mark.asyncio
async def test_insufficient_evidence_does_not_unlock(fake_path):
    # p 高但 n_obs < N_MIN → 内核判未过门 → 仍是 current，后继仍锁
    fake_path["progress"] = _progress(
        {"kc-a": BktPosterior(p_learned=0.99, sigma=0.01, n_obs=1)}
    )
    r = await mr.tool_get_mastery_path(None, uuid.uuid4(), now=1000.0)
    states = [n["state"] for n in r["nodes"]]
    assert states == ["current", "locked", "locked", "locked"]
    assert r["next"]["action"] == "practice" and r["next"]["kc_id"] == "kc-a"


@pytest.mark.asyncio
async def test_review_due_flag_and_next_action(fake_path):
    strong = BktPosterior(p_learned=0.99, sigma=0.01, n_obs=10)
    fake_path["progress"] = _progress(
        {"kc-a": strong},
        review=[ReviewTask(knowledge_point_id="kc-a", due_at=10.0, priority=1)],
    )
    r = await mr.tool_get_mastery_path(None, uuid.uuid4(), now=1000.0)
    a = r["nodes"][0]
    assert a["state"] == "mastered" and a["review_due"] is True
    assert r["pending_review_count"] == 1
    assert r["next"]["action"] == "review"  # 到期复习优先，但不改变锁状态
    assert r["current_kc_id"] == "kc-b"


@pytest.mark.asyncio
async def test_empty_path(fake_path):
    fake_path["kcs"] = []
    r = await mr.tool_get_mastery_path(None, uuid.uuid4())
    assert r["status"] == "empty" and r["nodes"] == []


@pytest.mark.asyncio
async def test_mastery_path_route_registered_and_requires_auth():
    from httpx import ASGITransport, AsyncClient

    from services.main import app

    assert "/mcp/GetMasteryPath" in set(app.openapi()["paths"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/mcp/GetMasteryPath", json={"student_id": str(uuid.uuid4())})
    assert r.status_code == 401
