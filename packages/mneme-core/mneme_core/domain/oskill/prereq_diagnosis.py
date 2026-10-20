"""mneme-core prereq_diagnosis — 自适应先修诊断（沿先修边回溯找薄弱根因）。

忠实移植自上游 cn-math-taxonomy ``diagnose/engine.js`` 的会话算法
（createSession / pickQuestion / applyAnswer / nextItem / replay / summarize / layout），
CC BY-NC 4.0，https://github.com/xiaoyang111222/cn-math-taxonomy 。

每个知识点最多 2 题：
  - 第一题对 -> 掌握（mastered/direct），并把所有尚未判定的祖先记为掌握（inferred），跳过；
  - 第一题错/不会 -> 再出一道同级或更容易的题：
      第二题对 -> 不稳（shaky），不向先修回溯；
      第二题也错 -> 薄弱（weak），把先修（hard 先于 soft，同级按 topics 顺序）压到出题栈顶，深度优先回溯。
结果：薄弱根因（weak 且其先修中没有 weak）+ 学习路径（根因∪不稳点及其子图内后代，去掉已掌握，
按年级低→高、同年级拓扑序先修在前）。

组合 ≥2 oprim：``prereq_graph``（建图/祖先/拓扑/可测性）+ ``prereq_judge.judge_question``
（``submit`` 先判题再推进会话）。Stateless：会话是可 JSON 序列化的纯数据（与上游 JS
会话结构字节级兼容），由调用方保存；所有函数都返回新会话、不修改入参。

**红线**：这里的 mastered/shaky/weak 只是本次诊断的结论，**不是 P(L)**。本模块不写
掌握度；需要回写 BKT 的作答必须由服务层逐题经 SubmitAnswer/process_interaction。
"""

from __future__ import annotations

import copy
import math
from typing import Any

from mneme_core.domain.oprim.prereq_graph import (
    DIFF_RANK,
    PrereqGraph,
    ancestor_set,
    is_testable,
    subgraph,
    topo_sort,
)
from mneme_core.domain.oprim.prereq_judge import judge_question

DEFAULT_LIMIT = 16
RESULTS = ("correct", "wrong", "skip")
_M32 = 0xFFFFFFFF

Session = dict[str, Any]


# ---------------------------------------------------------------- 可种子化伪随机（与 JS 逐位一致）

def hash_str(s: str) -> int:
    """FNV-1a over UTF-16 code units（与 JS charCodeAt 一致）。"""
    h = 2166136261
    data = s.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 16777619) & _M32
    return h


def mulberry32(a: int) -> Any:
    state = [a & _M32]

    def nxt() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & _M32
        x = state[0]
        t = ((x ^ (x >> 15)) * (1 | x)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return nxt


def rand01(seed: str, key: str) -> float:
    f = mulberry32(hash_str(f"{seed}|{key}"))
    f()
    return float(f())


def _seed_str(seed: Any) -> str:
    if seed is None:
        return "default"
    if isinstance(seed, bool):
        return "true" if seed else "false"
    if isinstance(seed, float) and seed.is_integer():
        return str(int(seed))
    return str(seed)


def _rank_of(q: dict[str, Any]) -> int:
    return DIFF_RANK.get(q.get("difficulty", ""), 1)


# ---------------------------------------------------------------- 会话

def create_session(graph: PrereqGraph, targets: list[str], *, limit: int | None = None,
                   seed: Any = None, avoid: list[str] | None = None) -> Session:
    ts = list(dict.fromkeys(targets))
    if not ts:
        raise ValueError("至少需要一个目标知识点")
    for tid in ts:
        if tid not in graph.by_id:
            raise ValueError("未知知识点：" + tid)
    lim = max(1, math.floor(DEFAULT_LIMIT if limit is None else limit))
    sub = subgraph(graph, ts)
    pos = {tid: i for i, tid in enumerate(sub["nodes"])}
    # 离目标最近（拓扑序最靠后）的目标先问；其余目标作为后备留在栈里
    stack = sorted([t for t in ts if is_testable(graph, t)], key=lambda t: -pos[t])
    return {
        "targets": ts, "limit": lim, "order": sub["nodes"], "status": {}, "stack": stack,
        "answers": [], "attempts": {}, "seed": _seed_str(seed),
        "avoid": list(dict.fromkeys(avoid or [])),
    }


def pick_question(graph: PrereqGraph, session: Session, tid: str, attempt: int) -> dict[str, Any] | None:
    """第一题优先没出过且非 advanced；第二题同级或更容易（basic > 同难度 > 更易 > 最易）。"""
    all_q = graph.bank.get(tid) or []
    tried = [a["qid"] for a in session["attempts"].get(tid, [])]
    pool = [q for q in all_q if q["id"] not in tried]
    if not pool:
        return None
    avoid = set(session.get("avoid") or [])

    def fresh_first(lst: list[dict[str, Any]]) -> list[dict[str, Any]]:
        f = [q for q in lst if q["id"] not in avoid]
        return f if f else lst

    if attempt <= 1:
        cand = fresh_first(pool)
        non_adv = [q for q in cand if _rank_of(q) < 2]
        if non_adv:
            cand = non_adv
    else:
        first = next((q for q in all_q if tried and q["id"] == tried[0]), None)
        r0 = _rank_of(first) if first else 1
        tiers = [
            [q for q in pool if _rank_of(q) == 0],
            [q for q in pool if _rank_of(q) == r0],
            [q for q in pool if _rank_of(q) < r0],
        ]
        hit = next((t for t in tiers if t), None)
        if hit:
            cand = fresh_first(hit)
        else:
            lo = min(_rank_of(q) for q in pool)
            cand = fresh_first([q for q in pool if _rank_of(q) == lo])
    idx = min(len(cand) - 1, math.floor(rand01(session["seed"], f"{tid}|{attempt}") * len(cand)))
    return cand[idx]


def apply_answer(graph: PrereqGraph, session: Session, tid: str, result: str,
                 text: Any = None) -> Session:
    """记录对 next_item 给出那道题的作答（correct / wrong / skip），返回新会话。"""
    if result not in RESULTS:
        raise ValueError("作答结果必须是 correct / wrong / skip")
    if tid not in graph.by_id:
        raise ValueError("未知知识点：" + tid)
    s = copy.deepcopy(session)
    if s["status"].get(tid):  # 对已有结论的点重新作答 = 重新开始
        del s["status"][tid]
        s["attempts"][tid] = []
    prev = s["attempts"].get(tid, [])
    q = pick_question(graph, s, tid, len(prev) + 1)
    rec: dict[str, Any] = {"id": tid, "qid": q["id"] if q else None, "result": result}
    if text is not None and text != "":
        rec["text"] = str(text)
    s["answers"].append(rec)
    s["attempts"][tid] = prev + [{"qid": rec["qid"], "result": result}]
    nth = len(s["attempts"][tid])
    if result == "correct":
        if nth == 1:
            s["status"][tid] = {"s": "mastered", "src": "direct"}
            for a in ancestor_set(graph, tid):
                if not s["status"].get(a):
                    s["status"][a] = {"s": "mastered", "src": "inferred"}
        else:
            s["status"][tid] = {"s": "shaky", "src": "direct"}
    elif nth == 1 and pick_question(graph, s, tid, 2):
        pass  # 第一题没过：等第二题再下结论
    else:
        s["status"][tid] = {"s": "weak", "src": "direct"}
        push = [p["id"] for p in graph.prereqs[tid]
                if is_testable(graph, p["id"]) and not s["status"].get(p["id"])]
        pushed = set(push)
        s["stack"] = push + [x for x in s["stack"] if x not in pushed]
    return s


def next_question(graph: PrereqGraph, session: Session) -> str | None:
    if len(session["answers"]) >= session["limit"]:
        return None
    for tid in session["stack"]:
        if not session["status"].get(tid) and is_testable(graph, tid):
            return str(tid)
    return None


def next_item(graph: PrereqGraph, session: Session) -> dict[str, Any] | None:
    """下一道要出的具体题：{topicId, question, attempt(1|2)}；结束返回 None。"""
    tid = next_question(graph, session)
    if not tid:
        return None
    attempt = len(session["attempts"].get(tid, [])) + 1
    q = pick_question(graph, session, tid, attempt)
    return {"topicId": tid, "question": q, "attempt": attempt} if q else None


def submit(graph: PrereqGraph, session: Session, answer: Any = None, *,
           result: str | None = None) -> dict[str, Any]:
    """判当前题并推进会话。

    ``result`` 显式给出（correct/wrong/skip，用于 manual 自评或"不会"）时不判题；否则用
    ``judge_question`` 判。判为 manual 时**不推进**，返回 ``needs_self_assessment=True`` +
    参考答案，由调用方让学生自评后带 ``result`` 再调一次。
    """
    item = next_item(graph, session)
    if not item:
        return {"session": session, "applied": False, "verdict": None, "item": None}
    verdict: dict[str, str] | None = None
    if result is None:
        verdict = judge_question(item["question"], answer)
        if verdict["verdict"] == "manual":
            return {"session": session, "applied": False, "verdict": verdict, "item": item,
                    "needs_self_assessment": True}
        result = verdict["verdict"]
    new = apply_answer(graph, session, item["topicId"], result, answer)
    return {"session": new, "applied": True, "verdict": verdict, "result": result, "item": item}


def replay(graph: PrereqGraph, targets: list[str], answers: list[dict[str, Any]], **opts: Any) -> Session:
    """由作答记录重建会话（刷新恢复、撤销、更正）。"""
    s = create_session(graph, targets, **opts)
    for a in answers:
        s = apply_answer(graph, s, a["id"], a["result"], a.get("text"))
    return s


def is_unconfirmed(session: Session, tid: str) -> bool:
    """第一题答错、但没来得及出第二题（题量用完）的点。"""
    a = session["attempts"].get(tid)
    return not session["status"].get(tid) and bool(a) and len(a) == 1 and a[0]["result"] != "correct"


def status_of(session: Session, tid: str) -> str:
    """mastered / shaky / weak / unknown（未复测的单错点按 weak）。"""
    st = session["status"].get(tid)
    if st:
        return str(st["s"])
    return "weak" if is_unconfirmed(session, tid) else "unknown"


def _grade_rank(graph: PrereqGraph, tid: str) -> int:
    t = graph.by_id.get(tid)
    g = t.get("grade") if t else None
    if not isinstance(g, (int, float)) or isinstance(g, bool):
        return 0
    return int(g * 2 + (1 if t and t.get("semester") == "下" else 0))


def summarize(graph: PrereqGraph, session: Session) -> dict[str, Any]:
    nodes = session["order"]

    def st(i: str) -> str:
        return status_of(session, i)

    mastered = [i for i in nodes if st(i) == "mastered"]
    shaky = [i for i in nodes if st(i) == "shaky"]
    weak = [i for i in nodes if st(i) == "weak"]
    unconfirmed = [i for i in weak if is_unconfirmed(session, i)]
    untested = [i for i in nodes if st(i) == "unknown"]
    roots = []
    for i in weak:
        if any(st(p["id"]) == "weak" for p in graph.prereqs[i]):
            continue
        unk = [p for p in graph.prereqs[i] if st(p["id"]) == "unknown"]
        roots.append({
            "id": i,
            "pendingPrereqs": [p["id"] for p in unk if is_testable(graph, p["id"])],
            "externalPrereqs": [p["id"] for p in unk if not is_testable(graph, p["id"])],
        })
    in_sub = set(nodes)
    queue = [r["id"] for r in roots] + shaky
    reach = set(queue)
    while queue:
        cur = queue.pop(0)
        for d in graph.dependents[cur]:
            if d["id"] in in_sub and d["id"] not in reach:
                reach.add(d["id"])
                queue.append(d["id"])
    root_set = {r["id"] for r in roots}
    target_set = set(session["targets"])
    topo_pos = {i: n for n, i in enumerate(nodes)}
    path = [{"id": i, "status": st(i), "isRoot": i in root_set, "isTarget": i in target_set}
            for i in nodes if i in reach and st(i) != "mastered"]
    path.sort(key=lambda p: (_grade_rank(graph, p["id"]), topo_pos[p["id"]]))
    pending = [i for i in session["stack"] if not session["status"].get(i) and is_testable(graph, i)]
    nxt = next_question(graph, session)
    return {
        "targets": list(session["targets"]), "asked": len(session["answers"]), "limit": session["limit"],
        "finished": nxt is None,
        "limitReached": len(session["answers"]) >= session["limit"] and len(pending) > 0,
        "mastered": mastered, "shaky": shaky, "weak": weak, "unconfirmed": unconfirmed,
        "untested": untested, "roots": roots, "path": path,
    }


def layout(graph: PrereqGraph, session: Session, summary: dict[str, Any]) -> dict[str, Any]:
    """路径图分层布局（先修在上）：边取传递约简，非直接先修边 direct=False。"""
    sel: list[str] = []

    def add(x: str) -> None:
        if x not in sel:
            sel.append(x)

    for p in summary["path"]:
        add(p["id"])
    for t in session["targets"]:
        add(t)
    for r in summary["roots"]:
        add(r["id"])
    for a in session["answers"]:
        add(a["id"])
    if len(sel) < 3:
        for t in session["targets"]:
            for p in graph.prereqs[t][:6]:
                add(p["id"])
    ids = topo_sort(graph, sel)
    edges: list[dict[str, Any]] = []
    for b in ids:
        anc = ancestor_set(graph, b)
        for a in ids:
            if a == b or a not in anc:
                continue
            if any(c not in (a, b) and c in anc and a in ancestor_set(graph, c) for c in ids):
                continue
            direct = next((p for p in graph.prereqs[b] if p["id"] == a), None)
            edges.append({"from": a, "to": b, "direct": bool(direct),
                          "strength": direct["strength"] if direct else "hard"})
    layer: dict[str, int] = {}
    for i in ids:
        lv = 0
        for e in edges:
            if e["to"] == i:
                lv = max(lv, layer[e["from"]] + 1)
        layer[i] = lv
    n_layers = max([layer[i] + 1 for i in ids] + [1])
    rows: list[list[str]] = [[] for _ in range(n_layers)]
    for i in ids:
        rows[layer[i]].append(i)
    slot = {i: n for r in rows for n, i in enumerate(r)}

    def bary(i: str, nbrs: list[str]) -> float:
        return float(slot[i]) if not nbrs else sum(slot[n] for n in nbrs) / len(nbrs)

    for _ in range(4):
        for lv in range(1, n_layers):
            rows[lv].sort(key=lambda i: bary(i, [e["from"] for e in edges if e["to"] == i]))
            for n, i in enumerate(rows[lv]):
                slot[i] = n
        for lv in range(n_layers - 2, -1, -1):
            rows[lv].sort(key=lambda i: bary(i, [e["to"] for e in edges if e["from"] == i]))
            for n, i in enumerate(rows[lv]):
                slot[i] = n
    root_set = {r["id"] for r in summary["roots"]}
    target_set = set(session["targets"])
    out_nodes = [{"id": i, "layer": lv, "col": n, "cols": len(r), "status": status_of(session, i),
                  "isTarget": i in target_set, "isRoot": i in root_set}
                 for lv, r in enumerate(rows) for n, i in enumerate(r)]
    return {"nodes": out_nodes, "edges": edges, "layers": n_layers,
            "maxCols": max([len(r) for r in rows] + [1])}
