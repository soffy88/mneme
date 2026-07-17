"""mneme-core quiz_selection — 组卷用的难度序列整形。

Pure function, no IO. 无 IRT 题库参数（题库无按题难度打分），"难度分布"退化为
KC 级难度（KnowledgePoint.difficulty，对齐 KnowledgeUnit.difficulty）排序整形。
"""

from __future__ import annotations

from typing import Literal

from mneme_core.oprim.models import KnowledgePoint

DifficultyCurve = Literal["ascending", "diagnostic", "mixed"]


def shape_by_difficulty(
    candidates: list[KnowledgePoint], *, curve: DifficultyCurve = "ascending"
) -> list[KnowledgePoint]:
    """按难度曲线重排候选 KC（不筛选、不去重，只重排序）。

    - ``ascending``：由易到难（常规巩固练习，脚手架式）。
    - ``diagnostic``：由难到易（诊断/摸底，快速定位能力上限）。
    - ``mixed``：低高交替 zigzag（简单的交错练习，避免同难度扎堆）。
    """
    ordered = sorted(candidates, key=lambda kp: kp.difficulty)
    if curve == "ascending":
        return ordered
    if curve == "diagnostic":
        return list(reversed(ordered))

    # mixed：从两端向中间交替取（最易、最难、次易、次难……）
    lo, hi = 0, len(ordered) - 1
    zigzag: list[KnowledgePoint] = []
    take_low = True
    while lo <= hi:
        if take_low:
            zigzag.append(ordered[lo])
            lo += 1
        else:
            zigzag.append(ordered[hi])
            hi -= 1
        take_low = not take_low
    return zigzag
