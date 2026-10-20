"""mneme-core prereq_graph — 先修知识图（DAG）的纯计算：建图、祖先、拓扑序、子图。

忠实移植自上游 cn-math-taxonomy ``diagnose/engine.js`` 的图部分
（buildGraph / ancestors / topoSort / subgraph / isTestable / gradeRank /
parseChapter / resolveTargets），CC BY-NC 4.0，
https://github.com/xiaoyang111222/cn-math-taxonomy 。

输入是与上游同构的 topics / deps / questions 列表（dict）；服务层可以从
``KnowledgeUnit``（cnmath:* 行的 prerequisites / soft_prerequisites /
rich_content）或 ``data/cn_math_taxonomy/*.json`` 组装出来。Pure functions, no IO。
"""

from __future__ import annotations

import re
from typing import Any

DIFF_RANK = {"basic": 0, "standard": 1, "advanced": 2}


def _q_num(q: dict[str, Any]) -> int:
    m = re.search(r"_q(\d+)$", str(q.get("id", "")))
    return int(m.group(1)) if m else 0


class PrereqGraph:
    """不可序列化的图对象（会话才是可 JSON 序列化的纯数据）。"""

    def __init__(self, topics: list[dict[str, Any]], by_id: dict[str, dict[str, Any]],
                 index: dict[str, int], prereqs: dict[str, list[dict[str, Any]]],
                 dependents: dict[str, list[dict[str, Any]]],
                 bank: dict[str, list[dict[str, Any]]], has_bank: bool) -> None:
        self.topics = topics
        self.by_id = by_id
        self.index = index
        self.prereqs = prereqs
        self.dependents = dependents
        self.bank = bank
        self.has_bank = has_bank
        self._anc: dict[str, set[str]] = {}
        self._visiting: dict[str, bool] = {}


def build_graph(topics: list[dict[str, Any]], deps: list[dict[str, Any]],
                questions: list[dict[str, Any]] | None = None) -> PrereqGraph:
    """deps: [{topicId, prerequisiteId, strength: hard|soft, reason?}]（topicId 依赖 prerequisiteId）。"""
    by_id: dict[str, dict[str, Any]] = {}
    index: dict[str, int] = {}
    for i, t in enumerate(topics):
        by_id[t["id"]] = t
        index[t["id"]] = i
    prereqs: dict[str, list[dict[str, Any]]] = {t["id"]: [] for t in topics}
    dependents: dict[str, list[dict[str, Any]]] = {t["id"]: [] for t in topics}
    seen: set[str] = set()
    for d in deps:
        tid, pid = d.get("topicId"), d.get("prerequisiteId")
        if tid not in by_id or pid not in by_id:
            continue
        k = f"{tid}<{pid}"
        if k in seen:
            continue
        seen.add(k)
        strength = "soft" if d.get("strength") == "soft" else "hard"
        prereqs[tid].append({"id": pid, "strength": strength, "reason": d.get("reason")})
        dependents[pid].append({"id": tid, "strength": strength})
    # 先修按 hard 优先、再 soft，同级按 topics 顺序，保证出题次序确定
    for tid in prereqs:
        prereqs[tid].sort(key=lambda e: (0 if e["strength"] == "hard" else 1) * 1_000_000 + index[e["id"]])
        dependents[tid].sort(key=lambda e: index[e["id"]])
    bank: dict[str, list[dict[str, Any]]] = {t["id"]: [] for t in topics}
    from_file = 0
    for q in questions if isinstance(questions, list) else []:
        if q and q.get("topicId") in bank and not by_id[q["topicId"]].get("external"):
            bank[q["topicId"]].append(q)
            from_file += 1
    for t in topics:
        dq = t.get("diagnostic_question")
        if not t.get("external") and not bank[t["id"]] and dq and dq.get("question"):
            bank[t["id"]].append({
                "id": t["id"] + "_q1", "topicId": t["id"], "difficulty": "standard", "type": "legacy",
                "prompt": dq["question"], "answer": dq.get("answer"), "explanation": "",
            })
    for tid in bank:
        bank[tid].sort(key=_q_num)
    return PrereqGraph(topics, by_id, index, prereqs, dependents, bank, from_file > 0)


def ancestor_set(graph: PrereqGraph, tid: str) -> set[str]:
    """严格祖先集合（不含自身），带缓存；有环抛 ValueError。"""
    memo = graph._anc
    if tid in memo:
        return memo[tid]
    if graph._visiting.get(tid):
        raise ValueError("先修图存在环：" + tid)
    graph._visiting[tid] = True
    out: set[str] = set()
    for p in graph.prereqs[tid]:
        out.add(p["id"])
        out |= ancestor_set(graph, p["id"])
    graph._visiting[tid] = False
    memo[tid] = out
    return out


def ancestors(graph: PrereqGraph, ids: str | list[str]) -> set[str]:
    out: set[str] = set()
    for tid in [ids] if isinstance(ids, str) else ids:
        out |= ancestor_set(graph, tid)
    return out


def topo_sort(graph: PrereqGraph, ids: Any) -> list[str]:
    """对节点子集做拓扑排序（先修在前）；同层按 topics 顺序，确定性。"""
    members = list(dict.fromkeys(ids))
    sset = set(members)
    indeg = {i: sum(1 for p in graph.prereqs[i] if p["id"] in sset) for i in members}
    ready = [i for i in members if indeg[i] == 0]
    order: list[str] = []
    while ready:
        ready.sort(key=lambda x: graph.index[x])
        cur = ready.pop(0)
        order.append(cur)
        for d in graph.dependents[cur]:
            if d["id"] not in sset:
                continue
            indeg[d["id"]] -= 1
            if indeg[d["id"]] == 0:
                ready.append(d["id"])
    if len(order) != len(sset):
        raise ValueError("拓扑排序失败：子图存在环")
    return order


def subgraph(graph: PrereqGraph, targets: list[str]) -> dict[str, Any]:
    """目标集合的先修子图：目标 + 所有祖先，拓扑序。"""
    members = list(dict.fromkeys(targets))
    for a in ancestors(graph, targets):
        if a not in members:
            members.append(a)
    return {"nodes": topo_sort(graph, members), "set": set(members)}


def is_testable(graph: PrereqGraph, tid: str) -> bool:
    t = graph.by_id.get(tid)
    return bool(t and not t.get("external") and graph.bank.get(tid))


def question_by_id(graph: PrereqGraph, qid: str | None) -> dict[str, Any] | None:
    m = re.match(r"^(.*)_q\d+$", qid or "")
    lst = graph.bank.get(m.group(1), []) if m else []
    return next((q for q in lst if q.get("id") == qid), None)


def grade_rank(graph: PrereqGraph, tid: str) -> int:
    """年级 ×2 + 学期（下=1），用于学习路径排序；没有 grade 时 0。"""
    t = graph.by_id.get(tid)
    g = t.get("grade") if t else None
    if not isinstance(g, (int, float)) or isinstance(g, bool):
        return 0
    return int(g * 2 + (1 if t and t.get("semester") == "下" else 0))


def parse_chapter(chapter: str | None) -> dict[str, str]:
    """"七上 第一章 有理数 1.1" / "一年级上册 第1单元 单元名" -> {volume, chapterNo, chapterName, section}。"""
    s = chapter or ""
    m = re.fullmatch(r"([一二三四五六])年级([上下])册 (第\d+单元) (.+)", s)
    if m:
        return {"volume": m[1] + m[2], "chapterNo": m[3], "chapterName": m[4], "section": ""}
    m = re.fullmatch(r"([一二三四五六])年级([上下])册 (综合与实践) (.+)", s)
    if m:
        return {"volume": m[1] + m[2], "chapterNo": m[3], "chapterName": m[4], "section": ""}
    m = re.fullmatch(r"(\S+) (第\S+章) (\S+?)(?: (\S+))?", s)
    if not m:
        return {"volume": "", "chapterNo": "", "chapterName": s, "section": ""}
    return {"volume": m[1], "chapterNo": m[2], "chapterName": m[3], "section": m[4] or ""}


def resolve_targets(raw_ids: str | list[str], aliases: dict[str, Any] | None) -> list[str]:
    """把旧 id（如已删除的 cnm_ext_*）按 id-aliases 展开成图中的知识点；未知 id 原样保留。"""
    amap = aliases or {}
    out: list[str] = []
    for tid in [raw_ids] if isinstance(raw_ids, str) else raw_ids:
        if not tid:
            continue
        spec = amap.get(tid)
        targets = None
        if isinstance(spec, dict) and isinstance(spec.get("targets"), list):
            targets = spec["targets"]
        elif isinstance(spec, list):
            targets = spec
        for x in targets if targets else [tid]:
            if x not in out:
                out.append(x)
    return out
