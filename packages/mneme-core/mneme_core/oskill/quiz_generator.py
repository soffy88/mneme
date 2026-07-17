"""mneme-core quiz_generator — 组卷（选 KC + 难度序列），不选具体题、不判分。

C2（W2C）：给定 KC 候选集 + 题量 + 难度分布 → 组卷。**这不是第二条出题路径**——
选出的每个 KC 仍经既有 RequestQuestion（AA.7 自足过滤 / AA.9 年级+选项清洗 /
AA.10 可判分子集过滤）逐题出题，SubmitAnswer + guard 判分回流 process_interaction
（S1 92.4% CI 门约束不变）。quiz_generator 只决定"考哪些 KC、什么顺序"。

组合 ≥2 oprim：``mastery_gate.is_mastered``（按当前 p_learned 筛除已过门 KC，
非 IRT——题库无按题难度参数）+ ``quiz_selection.shape_by_difficulty``（KC 级
难度整形，同样退化自 KnowledgeUnit.difficulty，非 IRT）。

Pure function, no IO——不碰 gate.pending_question，不判分，与量化/定性门控判据
完全解耦（FC-6：带 Mneme 题库/掌握度假设，留 mneme-core 私有）。
"""

from __future__ import annotations

from mneme_core.oprim.mastery_gate import is_mastered
from mneme_core.oprim.models import KnowledgePoint, LearningProgress
from mneme_core.oprim.quiz_selection import DifficultyCurve, shape_by_difficulty


def quiz_generator(
    progress: LearningProgress,
    candidates: list[KnowledgePoint],
    *,
    size: int,
    difficulty_curve: DifficultyCurve = "ascending",
    exclude_mastered: bool = True,
) -> list[KnowledgePoint]:
    """从候选 KC 里选 ``size`` 个组卷，按 ``difficulty_curve`` 排序。

    候选去重（按 id，保留首次出现）；已过门 KC 默认排除（``exclude_mastered``，
    组卷默认测未掌握项；诊断/摸底场景可传 False 全量覆盖）。候选不足 ``size``
    则返回全部（不报错、不补空）。
    """
    seen: set[str] = set()
    deduped: list[KnowledgePoint] = []
    for kp in candidates:
        if kp.id in seen:
            continue
        seen.add(kp.id)
        deduped.append(kp)

    pool = [
        kp for kp in deduped if not (exclude_mastered and is_mastered(progress, kp))
    ]
    ordered = shape_by_difficulty(pool, curve=difficulty_curve)
    return ordered[:size]
