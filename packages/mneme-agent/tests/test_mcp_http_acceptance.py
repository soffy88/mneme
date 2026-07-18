"""W2a W1–W3 —— MCP 工具面 HTTP 面验收（真 HTTP，不再只 tool_* 直调）。

W1: /mcp/* 七端点 HTTP 可达（非 404）。
W2: guard 三拒经 HTTP 返回 422、零写入。
W3: PoseQuestion / NextObjective 的 HTTP 响应体不含 expected。
需运行中的 api（/mcp 活）。harness 建/清 pilot。

AA.1 起 /mcp/* 每端点要求 JWT——本文件的 _post() 带 token（harness 侧用
obase.auth.create_access_token 现铸，跟真实 studio/agent 转发学生自己 token
同一验证路径，不是绕过鉴权）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

import pytest

from obase.auth import create_access_token
from sqlalchemy import text
from obase.db import SessionLocal
from services.models import User, UserRole

API = "http://localhost:8000"
KU004 = "renjiao-math-g10-a-ku004"
QUANT = "renjiao-math-g10-a-ku-二次函数的零点"
SECRET = "TOP_SECRET_ANSWER_9"


def _post(tool, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API}/mcp/{tool}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


async def _mk(sid):
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.commit()


async def _rm(sid):
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE users SET deleted_at=now()-interval '1 day' WHERE id=:i"),
            {"i": str(sid)},
        )
        await db.commit()
    async with SessionLocal() as db:
        from services.purge_service import purge_deleted_users

        await purge_deleted_users(db, grace_days=0)
        await db.commit()


@pytest.mark.asyncio
async def test_w1_seven_endpoints_reachable():
    sid = uuid.uuid4()
    await _mk(sid)
    token = create_access_token({"sub": str(sid)})
    try:
        qid = f"q-{uuid.uuid4().hex}"
        calls = {
            "NextObjective": {"student_id": str(sid), "kc_ids": [QUANT]},
            "GetKCInfo": {"kc_id": KU004},
            "CheckMastery": {"student_id": str(sid), "kc_id": QUANT},
            "GetReviewQueue": {"student_id": str(sid), "kc_ids": [QUANT]},
            "PoseQuestion": {
                "student_id": str(sid),
                "kc_id": QUANT,
                "question_id": qid,
                "prompt": "解 x^2-1=0",
                "expected": "x=1 或 x=-1",
                "qtype": "solve",
            },
            "SubmitAnswer": {
                "student_id": str(sid),
                "question_id": qid,
                "answer": "x=1,x=-1",
            },
            "ReportResult": {
                "student_id": str(sid),
                "kc_id": KU004,
                "is_correct": True,
                "verdict_source": "llm_verified",
                "evidence": {"ok": True},
            },
        }
        for tool, payload in calls.items():
            status, _ = _post(tool, payload, token=token)
            assert status != 404, f"/mcp/{tool} 不可达（404）"
    finally:
        await _rm(sid)


@pytest.mark.asyncio
async def test_w2_guard_three_rejects_422_http():
    sid = uuid.uuid4()
    await _mk(sid)
    token = create_access_token({"sub": str(sid)})
    try:
        # 1) agent 不得 deterministic
        s1, _ = _post(
            "ReportResult",
            {
                "student_id": str(sid),
                "kc_id": KU004,
                "is_correct": True,
                "verdict_source": "deterministic",
            },
            token=token,
        )
        # 2) llm_verified 无 evidence
        s2, _ = _post(
            "ReportResult",
            {
                "student_id": str(sid),
                "kc_id": KU004,
                "is_correct": True,
                "verdict_source": "llm_verified",
            },
            token=token,
        )
        # 3) 非法 source
        s3, _ = _post(
            "ReportResult",
            {
                "student_id": str(sid),
                "kc_id": KU004,
                "is_correct": True,
                "verdict_source": "bogus",
                "evidence": {"x": 1},
            },
            token=token,
        )
        assert s1 == 422 and s2 == 422 and s3 == 422, (s1, s2, s3)
        # 零写入：三拒后无定性过门记录
        async with SessionLocal() as db:
            n = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM gate.qualitative_mastery WHERE student_id=:s"
                    ),
                    {"s": str(sid)},
                )
            ).scalar_one()
            assert n == 0, "guard 拒绝后仍有写入"
    finally:
        await _rm(sid)


@pytest.mark.asyncio
async def test_w3_no_expected_leak_http():
    sid = uuid.uuid4()
    await _mk(sid)
    token = create_access_token({"sub": str(sid)})
    try:
        qid = f"q-{uuid.uuid4().hex}"
        s, pose = _post(
            "PoseQuestion",
            {
                "student_id": str(sid),
                "kc_id": QUANT,
                "question_id": qid,
                "prompt": "解 x^2-4=0",
                "expected": SECRET,
                "qtype": "solve",
            },
            token=token,
        )
        assert s == 200
        assert SECRET not in json.dumps(pose)  # PoseQuestion 响应
        _, nxt = _post(
            "NextObjective", {"student_id": str(sid), "kc_ids": [QUANT]}, token=token
        )
        assert SECRET not in json.dumps(nxt, ensure_ascii=False)  # NextObjective 响应
        assert "expected" not in json.dumps(nxt)
    finally:
        await _rm(sid)
