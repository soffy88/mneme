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
        for p in (ku.get("prerequisites") or []):
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


__all__ = ["topo_sort_by_prereq"]
