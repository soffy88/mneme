"""前置依赖拓扑排序（Kahn's 算法；存在环时把环上节点落到末尾）。

确定性 oprim 原子操作。此前内联在服务层 main.py（_topo_sort_kus），
违反"服务层不写本应属 oprim 的确定性算法"，上移至 oprim。
"""

from __future__ import annotations


def topo_sort_by_prereq(items: list[dict]) -> list[dict]:
    """对带 'id' 与 'prerequisites'(前置 id 列表) 的知识点列表做拓扑排序。

    返回排序后的列表；前置在前。环上/无法满足前置的节点稳定地落到末尾。
    """
    id_map = {k["id"]: k for k in items}
    in_deg = {k["id"]: 0 for k in items}
    adj: dict[str, list[str]] = {k["id"]: [] for k in items}
    for ku in items:
        for p in ku.get("prerequisites") or []:
            if p in id_map:
                in_deg[ku["id"]] += 1
                adj[p].append(ku["id"])
    queue = [k for k in items if in_deg[k["id"]] == 0]
    result: list[dict] = []
    while queue:
        ku = queue.pop(0)
        result.append(ku)
        for succ in adj[ku["id"]]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(id_map[succ])
    seen = {k["id"] for k in result}
    result.extend(k for k in items if k["id"] not in seen)
    return result


# ── 知识空间理论(KST/ALEKS) fringe 分类 ───────────────────────────────────────
# outer fringe = 前置全掌握、自身未开始 = "此刻可学"；前置未齐 = locked。
# 掌握门控：未达阈值的前置锁住下游新知（对齐 daily_plan 的 P4 门控阈值 0.6）。
MASTERY_THRESHOLD = 0.6
_NASCENT = 0.05  # p_mastery <= 此值视为"未开始"


def fringe_status(
    p_mastery: float | None,
    prerequisites: list[str] | None,
    mastery_map: dict[str, float | None],
    *,
    threshold: float = MASTERY_THRESHOLD,
) -> str:
    """单 KU 的知识空间状态（纯函数，确定性）：

    - ``mastered``  已掌握（p_mastery >= threshold）
    - ``learning``  在学中（_NASCENT < p_mastery < threshold）
    - ``learnable`` 可学（未开始，且所有前置均已掌握）= outer fringe
    - ``locked``    锁定（未开始，且存在未掌握的前置）
    """
    if p_mastery is not None and p_mastery >= threshold:
        return "mastered"
    if p_mastery is not None and p_mastery > _NASCENT:
        return "learning"
    prereqs_ok = all(
        (mastery_map.get(p) or 0.0) >= threshold for p in (prerequisites or [])
    )
    return "learnable" if prereqs_ok else "locked"


def annotate_fringe(
    items: list[dict],
    mastery_map: dict[str, float | None],
    *,
    threshold: float = MASTERY_THRESHOLD,
) -> list[dict]:
    """给每个带 'id'/'prerequisites'/'p_mastery' 的 KU dict 附 'fringe' 字段。"""
    return [
        {
            **it,
            "fringe": fringe_status(
                it.get("p_mastery"),
                it.get("prerequisites"),
                mastery_map,
                threshold=threshold,
            ),
        }
        for it in items
    ]


__all__ = [
    "topo_sort_by_prereq",
    "fringe_status",
    "annotate_fringe",
    "MASTERY_THRESHOLD",
]
