"""L3 · 先修回溯诊断（cn-math-taxonomy 一—九年级知识图，无状态会话）。

与 ``placement_service.cat_next``（Rasch θ 定位）并列的第二种定位：给一个目标知识点
（KnowledgeUnit ``cnmath:cnm_xxx``），每个知识点最多 2 题，答错就沿先修边（hard 先于 soft）
回溯，直到找到薄弱根因，输出按年级从低到高的学习路径。算法在
``mneme_core.domain.oskill.prereq_diagnosis``（移植自上游 engine.js，逐位一致），判题在
``mneme_core.domain.oprim.prereq_judge``；本模块只做装配：加载图、KU id 映射、把题目里的
参考答案对学生隐藏、把会话交还客户端保存（服务端不落库、无新表）。

图的来源与 ``services.cn_math_importer`` 写入 knowledge_units 的是同一份数据
（``data/cn_math_taxonomy``，上游 CC BY-NC 4.0），topic ``cnm_xxx`` ↔ KU ``cnmath:cnm_xxx``。

红线：诊断结论（mastered/shaky/weak）**不是 P(L)**，这里不写 kc_mastery、不调
process_interaction。会话里不放 student_id（seed 用随机串），避免 PII 进客户端存档。
"""

from __future__ import annotations

import json
import os
import secrets
from functools import lru_cache
from typing import Any

from mneme_core.domain.oprim import prereq_graph as pg
from mneme_core.domain.oskill import prereq_diagnosis as pd

KU_PREFIX = "cnmath:"
DATA_DIR = os.getenv(
    "CN_MATH_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cn_math_taxonomy"),
)
# 发给学生的题目里只保留这些字段（answer / accept / explanation / verify 在作答后才给）
_PUBLIC_Q_FIELDS = ("id", "topicId", "difficulty", "type", "prompt", "choices", "unordered")


class PrereqDiagnosisError(ValueError):
    """输入错误（未知知识点、会话损坏等）；路由层转 400/404。"""


def _load(name: str, default: Any = None) -> Any:
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    topics = _load("topics.json")
    deps = _load("dependencies.json", [])
    questions = _load("questions.json", [])
    standards = _load("cn-curriculum-standards.json", {"items": []})
    aliases = _load("id-aliases.json", {"aliases": {}})
    return {
        "graph": pg.build_graph(topics, deps, questions),
        "standards": {s["id"]: s for s in standards.get("items", [])},
        "aliases": aliases.get("aliases", {}),
    }


def graph() -> pg.PrereqGraph:
    g: pg.PrereqGraph = _bundle()["graph"]
    return g


def to_topic_id(ref: str) -> str:
    """接受 ``cnmath:cnm_221`` / ``cnm_221``，返回 topic id。"""
    return ref[len(KU_PREFIX):] if ref.startswith(KU_PREFIX) else ref


def to_ku_id(topic_id: str) -> str:
    return KU_PREFIX + topic_id


def _brief(tid: str) -> dict[str, Any]:
    t = graph().by_id[tid]
    return {
        "id": tid, "ku_id": to_ku_id(tid), "name": t.get("name"), "grade": t.get("grade"),
        "semester": t.get("semester"), "chapter": t.get("chapter"), "domain": t.get("domain"),
    }


def search_topic(q: str, limit: int = 10) -> list[dict[str, Any]]:
    """按名称/描述/章节子串检索（名称精确 > 名称包含 > 其他字段包含）。"""
    q = (q or "").strip().lower()
    if not q:
        return []
    scored: list[tuple[int, int, str]] = []
    g = graph()
    for t in g.topics:
        name = str(t.get("name", "")).lower()
        if t["id"].lower() == q or name == q:
            s = 0
        elif q in name:
            s = 1
        elif q in str(t.get("description", "")).lower() or q in str(t.get("chapter", "")).lower():
            s = 2
        else:
            continue
        scored.append((s, g.index[t["id"]], t["id"]))
    scored.sort()
    return [_brief(tid) for _, _, tid in scored[: max(1, limit)]]


def get_topic(ref: str) -> dict[str, Any]:
    tid = to_topic_id(ref)
    g = graph()
    if tid not in g.by_id:
        alias = _bundle()["aliases"].get(tid)
        if alias:
            return {"id": tid, "deprecated": True, "name": alias.get("name"),
                    "alias_targets": [to_ku_id(x) for x in alias.get("targets", [])]}
        raise PrereqDiagnosisError("未知知识点：" + ref)
    t = g.by_id[tid]
    stds = _bundle()["standards"]
    return {
        **_brief(tid),
        "type": t.get("type"),
        "description": t.get("description"),
        "mastery_criteria": t.get("mastery_criteria", []),
        "standards": [{**s, "text": stds.get(s.get("id"), {}).get("text")} for s in t.get("standards", [])],
        "prerequisites": [{**_brief(p["id"]), "strength": p["strength"], "reason": p.get("reason")}
                          for p in g.prereqs[tid]],
        "n_questions": len(g.bank.get(tid, [])),
    }


def get_prerequisites(ref: str, recursive: bool = True) -> list[dict[str, Any]]:
    """直接先修（带 hard/soft）或全部祖先（拓扑序，先修在前）。"""
    tid = to_topic_id(ref)
    g = graph()
    if tid not in g.by_id:
        raise PrereqDiagnosisError("未知知识点：" + ref)
    if not recursive:
        return [{**_brief(p["id"]), "strength": p["strength"]} for p in g.prereqs[tid]]
    return [_brief(x) for x in pg.topo_sort(g, pg.ancestors(g, tid))]


def _public_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    q = item["question"]
    return {
        "topic": _brief(item["topicId"]),
        "attempt": item["attempt"],
        "question": {k: q[k] for k in _PUBLIC_Q_FIELDS if k in q},
    }


def _report(session: dict[str, Any]) -> dict[str, Any]:
    g = graph()
    s = pd.summarize(g, session)
    return {
        "finished": s["finished"], "asked": s["asked"], "limit": s["limit"],
        "limit_reached": s["limitReached"],
        "weak_roots": [{**_brief(r["id"]), "pending_prereqs": [to_ku_id(x) for x in r["pendingPrereqs"]]}
                       for r in s["roots"]],
        "learning_path": [{**_brief(p["id"]), "status": p["status"], "is_root": p["isRoot"],
                           "is_target": p["isTarget"]} for p in s["path"]],
        "weak": [to_ku_id(x) for x in s["weak"]],
        "shaky": [to_ku_id(x) for x in s["shaky"]],
        "unconfirmed": [to_ku_id(x) for x in s["unconfirmed"]],
        "mastered_count": len(s["mastered"]),
        "untested_count": len(s["untested"]),
        "is_mastery_estimate": False,  # 诊断结论，不是 P(L)
    }


def _check_session(session: Any) -> dict[str, Any]:
    keys = ("targets", "limit", "order", "status", "stack", "answers", "attempts", "seed")
    if not isinstance(session, dict) or any(k not in session for k in keys):
        raise PrereqDiagnosisError("会话无效")
    g = graph()
    if any(t not in g.by_id for t in session["targets"]):
        raise PrereqDiagnosisError("会话含未知知识点")
    return session


def start(targets: list[str], *, limit: int | None = None, seed: str | None = None) -> dict[str, Any]:
    """开会话：targets 可是 KU id / topic id / 已废弃的 cnm_ext_*（按 id-aliases 展开）。"""
    raw = [to_topic_id(t) for t in targets]
    tids = pg.resolve_targets(raw, _bundle()["aliases"])
    try:
        session = pd.create_session(graph(), tids, limit=limit,
                                    seed=seed or secrets.token_hex(8))
    except ValueError as e:
        raise PrereqDiagnosisError(str(e)) from e
    return {"session": session, "next": _public_item(pd.next_item(graph(), session)),
            "report": _report(session)}


def answer(session: Any, user_answer: Any = None, result: str | None = None) -> dict[str, Any]:
    """交当前题的答案（或 result=correct/wrong/skip 自评/不会），返回新会话 + 下一题 + 报告。

    判为 manual（代数式/文字题不可靠）时会话不推进，返回参考答案让学生自评后带 result 重交。
    """
    s = _check_session(session)
    if result is not None and result not in pd.RESULTS:
        raise PrereqDiagnosisError("result 必须是 correct / wrong / skip")
    out = pd.submit(graph(), s, user_answer, result=result)
    item = out.get("item")
    feedback = None
    if item:
        q = item["question"]
        feedback = {"verdict": out.get("verdict"), "result": out.get("result"),
                    "answer": q.get("answer"), "explanation": q.get("explanation")}
    new = out["session"]
    return {
        "session": new,
        "applied": out["applied"],
        "needs_self_assessment": bool(out.get("needs_self_assessment")),
        "feedback": feedback,
        "next": _public_item(pd.next_item(graph(), new)),
        "report": _report(new),
    }
