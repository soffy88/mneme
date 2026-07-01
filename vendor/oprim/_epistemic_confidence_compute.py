"""oprim.epistemic_confidence_compute — Weighted epistemic confidence calculation.

3O layer: oprim (形态1 纯数学).
"""

from __future__ import annotations

# 默认 grade 权重 (可覆盖)
DEFAULT_GRADE_WEIGHTS: dict[str, float] = {
    "proven": 1.0,
    "high": 0.8,
    "moderate": 0.6,
    "low": 0.4,
    "unverified": 0.2,
    "contradicted": 0.0,
}


def epistemic_confidence_compute(
    *,
    grades: list[str],
    weights: dict[str, float] | None = None,
    unknown_grade_weight: float = 0.2,
) -> float:
    """按 grade 加权算整体认知可信度 (纯计算, 替代 LLM 自评).

    输入一组检索 KU 的 grade → 输出加权整体可信度 [0,1]。
    跨项目复用: Tide 信号可信度 / Stratum 引用置信 / Aegis 根因可信度。

    Args:
        grades: KU 的 grade 列表 (如 ["proven", "high", "low"]).
        weights: grade→权重映射, None 用 DEFAULT_GRADE_WEIGHTS. 调用方可传自己的体系.
        unknown_grade_weight: grades 中出现 weights 未定义的 grade 时的兜底权重.

    Returns:
        float: 整体可信度 [0,1], grades 为空返回 0.0.

    Raises:
        ValueError: weights 含越界值 (不在 [0,1]).

    Example:
        >>> epistemic_confidence_compute(grades=["proven", "high", "moderate"])
        0.8
        >>> epistemic_confidence_compute(grades=[])
        0.0
    """
    if not grades:
        return 0.0

    active_weights = weights if weights is not None else DEFAULT_GRADE_WEIGHTS

    # Check for out-of-bounds weights
    for g, w in active_weights.items():
        if not (0.0 <= w <= 1.0):
            raise ValueError(f"Weight for grade '{g}' is out of bounds [0, 1]: {w}")

    total_confidence = 0.0
    for grade in grades:
        weight = active_weights.get(grade, unknown_grade_weight)
        total_confidence += weight

    return float(total_confidence / len(grades))
