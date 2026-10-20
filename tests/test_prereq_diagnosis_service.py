"""先修回溯诊断服务层 + MCP 工具 + 红线/数据来源守卫（不碰 DB）。"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib

import pytest
from fastapi import HTTPException

from services import prereq_diagnosis_service as pds
from services.mcp_router import (
    tool_get_math_topic,
    tool_search_math_topic,
    tool_start_prereq_diagnosis,
    tool_submit_prereq_diagnosis_answer,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_search_and_get_topic():
    hits = tool_search_math_topic("配方法")["topics"]
    assert hits and hits[0]["id"] == "cnm_221" and hits[0]["ku_id"] == "cnmath:cnm_221"
    t = tool_get_math_topic("cnmath:cnm_221", recursive_prereqs=True)
    assert [p["id"] for p in t["prerequisites"]] == ["cnm_148", "cnm_220"]
    assert t["prerequisites"][0]["name"] == "完全平方公式" and t["prerequisites"][0]["strength"] == "hard"
    assert t["standards"] and t["standards"][0]["text"]
    allp = [p["id"] for p in t["all_prerequisites"]]
    assert allp.index("cnm_148") > 0 and "cnm_221" not in allp
    old = tool_get_math_topic("cnm_ext_002")
    assert old["deprecated"] and all(x.startswith("cnmath:cnm_p") for x in old["alias_targets"])
    with pytest.raises(HTTPException):
        tool_get_math_topic("nope")


def test_start_hides_answers_and_session_has_no_pii():
    r = tool_start_prereq_diagnosis(["cnmath:cnm_221"])
    q = r["next"]["question"]
    assert r["next"]["topic"]["id"] == "cnm_221" and r["next"]["attempt"] == 1
    assert "answer" not in q and "explanation" not in q and "accept" not in q
    assert set(r["session"]) == {"targets", "limit", "order", "status", "stack", "answers", "attempts", "seed", "avoid"}
    json.dumps(r["session"])  # JSON 可序列化
    assert r["report"]["is_mastery_estimate"] is False


def test_demo_cnm_221_wrong_backtracks_to_perfect_square():
    r = tool_start_prereq_diagnosis(["cnm_221"], limit=40)
    s = r["session"]
    asked = []
    for _ in range(60):
        nxt = r["next"]
        if not nxt:
            break
        tid = nxt["topic"]["id"]
        asked.append(tid)
        res = "wrong" if tid in ("cnm_221", "cnm_148") else "correct"
        r = tool_submit_prereq_diagnosis_answer(s, result=res)
        s = r["session"]
        assert r["applied"]
    assert asked[:4] == ["cnm_221", "cnm_221", "cnm_148", "cnm_148"]
    assert "cnm_220" in asked
    rep = r["report"]
    assert rep["finished"]
    assert [x["name"] for x in rep["weak_roots"]] == ["完全平方公式"]
    path = [p["id"] for p in rep["learning_path"]]
    assert path[0] == "cnm_148" and path[-1] == "cnm_221"
    assert "cnmath:cnm_148" in rep["weak"]


def test_judged_answer_and_manual_self_assessment():
    r = tool_start_prereq_diagnosis(["cnm_p001"], limit=5)
    q = r["next"]["question"]
    full = next(x for x in pds.graph().bank["cnm_p001"] if x["id"] == q["id"])
    ok = tool_submit_prereq_diagnosis_answer(r["session"], answer=full["answer"])
    assert ok["applied"] and ok["feedback"]["verdict"]["verdict"] == "correct"
    assert ok["report"]["finished"] and ok["next"] is None
    # 自评：result 显式给出时不判题直接推进
    r2 = tool_start_prereq_diagnosis(["cnm_p001"], limit=5)
    sk = tool_submit_prereq_diagnosis_answer(r2["session"], result="skip")
    assert sk["applied"] and sk["feedback"]["verdict"] is None and sk["next"]["attempt"] == 2


def test_bad_session_rejected():
    with pytest.raises(HTTPException):
        tool_submit_prereq_diagnosis_answer({"foo": 1}, answer="1")
    s = tool_start_prereq_diagnosis(["cnm_221"])["session"]
    with pytest.raises(HTTPException):
        tool_submit_prereq_diagnosis_answer(s, result="maybe")


def test_upstream_snapshot_is_verbatim_and_licensed():
    d = ROOT / "data" / "cn_math_taxonomy"
    up = json.loads((d / "UPSTREAM.json").read_text(encoding="utf-8"))
    assert up["license"] == "CC BY-NC 4.0" and up["repo"].endswith("cn-math-taxonomy")
    for name, sha in up["sha256"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == sha, name
    assert "Attribution-NonCommercial 4.0" in (d / "LICENSE").read_text(encoding="utf-8")
    assert "xiaoyang111222" in (d / "NOTICE.md").read_text(encoding="utf-8")


def test_diagnosis_never_touches_mastery_write_path():
    """红线：诊断链路不 import 认知写路径、不写 kc_mastery（掌握度唯一路径）。"""
    files = [
        ROOT / "services/prereq_diagnosis_service.py",
        ROOT / "packages/mneme-core/mneme_core/domain/oskill/prereq_diagnosis.py",
        ROOT / "packages/mneme-core/mneme_core/domain/oprim/prereq_graph.py",
        ROOT / "packages/mneme-core/mneme_core/domain/oprim/prereq_judge.py",
    ]
    banned = ("cognitive", "process_interaction", "kc_mastery", "bkt", "fsrs", "sqlalchemy", "models")
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for m in mods:
                    assert not any(b in m for b in banned), f"{f.name} imports {m}"
