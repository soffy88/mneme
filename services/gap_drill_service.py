"""gap_drill_service.py — 缺口单点练闭环（认知负荷①）

把已有的四件套串成一条可调用链路（此前组件都在、闭环未装配）：

  先修诊断 weak_roots（prereq_diagnosis_service）
    → 针对「未满足的前置 KU」生成 5–10 道只练这一步的单点微题
    → 逐题确定性判分（题库题走 prereq_judge；变式题走 ask_kernels 内核）
    → 逐题经 SubmitAnswer 唯一写路径回写 BKT（装配在 mcp_router，
      本模块不写 kc_mastery、不自判掌握度——红线同 prereq_diagnosis）
    → 练完用 evaluate_return 只读 KCMastery 核对门禁（GATE / mastery_confirmed）
    → 过门禁才回到原复合题，并标注「刚补的就是这一步」

题目来源：先用 cn-math-taxonomy 题库里该前置 topic 的原题；不够数时用
``ask_kernels.variants.make_variant`` 对原题做确定性变式（种子由会话种子
crc32 派生，跨进程/跨请求可复现）。变式答案**不进客户端会话**：判分与回写
时在服务端按 (base_question_id, seed) 重新生成同一变式再取其内核解。

会话形态与 prereq_diagnosis 一致：服务端不落库、客户端持有、无 student_id
（避免 PII 进客户端存档）、无新表。
"""

from __future__ import annotations

import secrets
import zlib
from typing import Any, Optional

from mneme_core.domain.oprim import prereq_judge as pj

from services import prereq_diagnosis_service as pds

MIN_ITEMS = 5
MAX_ITEMS = 10
DEFAULT_ITEMS = 8
RESULTS = ("correct", "wrong", "skip")
# 上游题型 → SubmitAnswer 判分题型（与 mcp_router._PREREQ_QTYPE 同义；
# 变式题一律内核数值题 → fill）
_SUBMIT_QTYPE = {"numeric": "fill", "choice": "choice", "short": "short"}
_PUBLIC_Q_FIELDS = ("id", "topicId", "difficulty", "type", "prompt", "choices", "unordered")


class GapDrillError(ValueError):
    """输入错误（无弱根、题目不足、会话损坏等）；路由层转 400。"""


# ── 目标 topic 解析 ──────────────────────────────────────────────────────

def _target_topics(weak_roots: list[dict]) -> list[str]:
    """weak_roots（诊断报告条目）→ 要单练的前置 topic 列表（去重保序）。

    条目里的 pending_prereqs 是「未满足的前置 KU」——单练的对象是它们；
    条目没有 pending 时退化为练这个弱根本身。
    """
    g = pds.graph()
    out: list[str] = []
    for root in weak_roots or []:
        if not isinstance(root, dict):
            continue
        pending = root.get("pending_prereqs") or root.get("pendingPrereqs") or []
        refs = list(pending) if pending else [root.get("ku_id") or root.get("id")]
        for ref in refs:
            if not ref:
                continue
            tid = pds.to_topic_id(str(ref))
            if tid in g.by_id and tid not in out:
                out.append(tid)
    return out


def _variant_seed(session_seed: str, base_qid: str, round_no: int) -> int:
    """跨进程稳定的变式种子（禁用 hash()：进程间随机化会让变式不可复现）。"""
    return zlib.crc32(f"{session_seed}:{base_qid}:{round_no}".encode()) & 0xFFFFFFFF


def _make_variant(base_q: dict, seed: int) -> Optional[dict]:
    from services.ask_kernels.variants import make_variant

    try:
        return make_variant(str(base_q.get("prompt") or ""), seed)
    except Exception:  # noqa: BLE001 变式是尽力扩展，失败就少一道
        return None


def _variant_solution(base_q: dict, seed: int) -> Optional[dict]:
    """服务端重算同一变式，取内核解（answer_value/answer_kind）。"""
    v = _make_variant(base_q, seed)
    if not v:
        return None
    sol = v.get("solution") or {}
    if not sol.get("answer_value"):
        return None
    return {"text": v["text"], **sol}


# ── 题目装配 ────────────────────────────────────────────────────────────

def build_drill(
    weak_roots: list[dict],
    *,
    original: Optional[dict] = None,
    count: int = DEFAULT_ITEMS,
    seed: Optional[str] = None,
) -> dict:
    """开一节单点练：返回 {session, next, targets, available}。

    original = 学生卡住的那道复合题的引用 {ku_id, question_id?, label?}，
    只做回程标注用，本模块不解析它。
    """
    count = max(MIN_ITEMS, min(MAX_ITEMS, int(count or DEFAULT_ITEMS)))
    topics = _target_topics(weak_roots)
    if not topics:
        raise GapDrillError("没有可单练的前置知识点（weak_roots 为空或未知）")
    g = pds.graph()
    session_seed = seed or secrets.token_hex(8)

    refs: list[dict] = []
    banks: list[list[dict]] = [list(g.bank.get(t, [])) for t in topics]
    # 第一轮：各 topic 题库原题交错排（相邻不同 KU，顺带满足交错直觉）
    for i in range(max((len(b) for b in banks), default=0)):
        for t, bank in zip(topics, banks):
            if i < len(bank):
                q = bank[i]
                refs.append({"kind": "bank", "question_id": q["id"], "topic_id": t})
            if len(refs) >= count:
                break
        if len(refs) >= count:
            break
    # 第二轮：不够数 → 确定性变式扩展（最多 3 轮，变不出来就如实少给）
    round_no = 1
    while len(refs) < count and round_no <= 3:
        progressed = False
        for t, bank in zip(topics, banks):
            for q in bank:
                if len(refs) >= count:
                    break
                v_seed = _variant_seed(session_seed, q["id"], round_no)
                v = _make_variant(q, v_seed)
                if v:
                    refs.append({
                        "kind": "variant",
                        "question_id": f"var:{q['id']}:{round_no}",
                        "base_question_id": q["id"],
                        "variant_seed": v_seed,
                        "topic_id": t,
                        "prompt": v["text"],
                    })
                    progressed = True
            if len(refs) >= count:
                break
        if not progressed:
            break
        round_no += 1

    if not refs:
        raise GapDrillError("目标前置知识点暂无可用题目")

    session = {
        "version": 1,
        "seed": session_seed,
        "original": original or {},
        "targets": [pds.to_ku_id(t) for t in topics],
        "items": refs,
        "index": 0,
        "results": [],
        "finished": False,
    }
    return {
        "session": session,
        "next": _public_item(_current_ref(session)),
        "targets": [
            {"ku_id": pds.to_ku_id(t), "name": g.by_id[t].get("name")} for t in topics
        ],
        "available": len(refs),
        "requested": count,
    }


# ── 会话推进 ────────────────────────────────────────────────────────────

def _check_session(session: Any) -> dict:
    keys = ("version", "seed", "original", "targets", "items", "index", "results", "finished")
    if not isinstance(session, dict) or any(k not in session for k in keys):
        raise GapDrillError("会话无效")
    if not isinstance(session["items"], list) or not session["items"]:
        raise GapDrillError("会话无题目")
    return session


def _current_ref(session: dict) -> Optional[dict]:
    idx = int(session.get("index") or 0)
    items = session["items"]
    return items[idx] if 0 <= idx < len(items) else None


def _public_item(ref: Optional[dict]) -> Optional[dict]:
    if not ref:
        return None
    if ref["kind"] == "variant":
        q = {"id": ref["question_id"], "topicId": ref["topic_id"],
             "type": "numeric", "prompt": ref.get("prompt") or ""}
    else:
        base = pds.question_by_id(ref["question_id"]) or {}
        q = {k: base[k] for k in _PUBLIC_Q_FIELDS if k in base}
    return {"topic_id": ref["topic_id"], "ku_id": pds.to_ku_id(ref["topic_id"]), "question": q}


def expected_answer(ref: dict) -> Optional[dict]:
    """服务端取某题的期望答案（判分/回写专用，绝不外发）。

    返回 {expected, submit_qtype, prompt}；取不到（变式重算失败等）返回 None。
    """
    if ref.get("kind") == "variant":
        base = pds.question_by_id(str(ref.get("base_question_id")))
        if base is None:
            return None
        sol = _variant_solution(base, int(ref.get("variant_seed") or 0))
        if sol is None:
            return None
        return {"expected": str(sol["answer_value"]), "submit_qtype": "fill",
                "prompt": sol["text"], "answer_kind": sol.get("answer_kind")}
    q = pds.question_by_id(str(ref.get("question_id")))
    if q is None or not q.get("answer"):
        return None
    return {"expected": str(q["answer"]),
            "submit_qtype": _SUBMIT_QTYPE.get(str(q.get("type"))),
            "prompt": str(q.get("prompt") or "")}


def _grade(ref: dict, user_answer: Any) -> str:
    """确定性判分 → correct / wrong / manual（判不了交自评，不猜）。"""
    if ref.get("kind") == "variant":
        exp = expected_answer(ref)
        if exp is None:
            return "manual"
        from services.ask_kernels.variants import grade_answer

        verdict = grade_answer(
            str(user_answer or ""), exp["expected"], exp.get("answer_kind") or "num"
        )
        return {True: "correct", False: "wrong", None: "manual"}[verdict]
    q = pds.question_by_id(str(ref.get("question_id"))) or {}
    return pj.judge_question(q, user_answer)["verdict"]


def answer_drill(
    session: Any, user_answer: Any = None, result: Optional[str] = None
) -> dict:
    """交当前题答案（或 result=correct/wrong/skip 自评），推进会话。

    自动判不了（manual）且未给 result 时不推进：返回参考答案供学生对照自评
    （与 prereq 诊断同一契约；答案只在作答后给出）。自评/skip 不回写掌握度
    ——由装配层按 answered.self_assessed 决定，红线同诊断。
    """
    s = _check_session(session)
    if result is not None and result not in RESULTS:
        raise GapDrillError("result 必须是 correct / wrong / skip")
    if s.get("finished"):
        raise GapDrillError("本节单点练已完成")
    ref = _current_ref(s)
    if ref is None:
        raise GapDrillError("会话已无待答题目")

    self_assessed = result is not None
    if self_assessed:
        verdict = result
    else:
        verdict = _grade(ref, user_answer)
        if verdict == "manual":
            exp = expected_answer(ref)
            base = pds.question_by_id(
                str(ref.get("base_question_id") or ref.get("question_id"))
            ) or {}
            return {
                "session": s, "applied": False, "answered": None,
                "needs_self_assessment": True,
                "feedback": {"verdict": "manual",
                             "answer": exp["expected"] if exp else None,
                             "explanation": base.get("explanation")},
                "next": _public_item(ref),
                "progress": _progress(s), "finished": False,
            }

    new = {**s, "items": list(s["items"]), "results": list(s["results"])}
    new["results"].append({
        "question_id": ref["question_id"], "ku_id": pds.to_ku_id(ref["topic_id"]),
        "result": verdict,
    })
    new["index"] = int(s["index"]) + 1
    new["finished"] = new["index"] >= len(new["items"])
    answered = {
        "kind": ref["kind"],
        "question_id": ref["question_id"],
        "base_question_id": ref.get("base_question_id"),
        "variant_seed": ref.get("variant_seed"),
        "topic_id": ref["topic_id"],
        "ku_id": pds.to_ku_id(ref["topic_id"]),
        "type": "numeric" if ref["kind"] == "variant" else (
            (pds.question_by_id(ref["question_id"]) or {}).get("type")
        ),
        "attempt": 1,
        "seed": str(s.get("seed") or ""),
        "self_assessed": self_assessed,
    }
    base = pds.question_by_id(str(ref.get("base_question_id") or ref.get("question_id"))) or {}
    exp = expected_answer(ref)
    return {
        "session": new,
        "applied": True,
        "answered": answered,
        "needs_self_assessment": False,
        "feedback": {"verdict": verdict, "result": verdict,
                     "answer": exp["expected"] if exp else base.get("answer"),
                     "explanation": base.get("explanation")},
        "next": _public_item(_current_ref(new)),
        "progress": _progress(new),
        "finished": bool(new["finished"]),
    }


def _progress(s: dict) -> dict:
    results = s.get("results") or []
    return {
        "done": len(results),
        "total": len(s.get("items") or []),
        "correct": sum(1 for r in results if r.get("result") == "correct"),
    }


# ── 过门禁 → 回原题（只读核对，不自判掌握度）────────────────────────────

async def evaluate_return(db, student_id, session: Any) -> dict:
    """练完核对每个目标 KU 是否已过门禁（只读 KCMastery，判定单源 GATE）。

    ready = mastery_confirmed 或 p_mastery >= GATE（services.learner_model
    单源常量）。本函数不写任何状态；未过门禁时如实返回并建议继续练或走
    既有掌握裁决（services.routers.cognitive 的 mastery gate 接口）。
    """
    from sqlalchemy import select

    from services.learner_model import GATE
    from services.models import KCMastery

    s = _check_session(session)
    per_ku = []
    for ku_id in s["targets"]:
        row = (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point == ku_id,
                )
            )
        ).scalar_one_or_none()
        p = float(row.p_mastery) if row and row.p_mastery is not None else None
        confirmed = bool(row and row.mastery_confirmed)
        per_ku.append({
            "ku_id": ku_id, "p_mastery": p, "mastery_confirmed": confirmed,
            "ready": confirmed or (p is not None and p >= GATE),
        })
    ready = bool(per_ku) and all(x["ready"] for x in per_ku)
    return {
        "finished": bool(s.get("finished")),
        "ready": ready,
        "per_ku": per_ku,
        "original": s.get("original") or {},
        "annotation": "刚补的就是这一步" if ready else None,
        "next_action": "return_to_original" if ready else "continue_drill_or_mastery_gate",
    }
