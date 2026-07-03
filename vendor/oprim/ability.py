"""L3 · 能力估计（Rasch θ）。自适应定位(CAT)与 ZPD 难度带的心脏。纯函数，确定性。

按 Rasch/1PL：P(答对) = sigmoid(scale·(θ − b))，b=题目难度∈[0,1]，θ=学生能力∈[0,1]。
从一批 (难度, 对错) 响应用最大似然网格估 θ 与标准误 SE(用 Fisher 信息)。
用途：入学定位、冷启动初始化、L1 get_zpd_band 由启发式升级为 θ 驱动。
"""

from __future__ import annotations

import math

_SCALE = 2.0  # 难度[0,1] → logit 斜率（缓，使 CAT 约 20–30 题到 SE<0.10 停）


def _p_correct(theta: float, b: float, scale: float = _SCALE) -> float:
    return 1.0 / (1.0 + math.exp(-scale * (theta - b)))


def estimate_ability(
    responses: list[tuple[float, bool]], *, scale: float = _SCALE
) -> dict:
    """从 [(难度 b∈[0,1], 是否答对)] 估学生能力 θ。

    Returns {theta∈[0,1], se, n}。无响应 → θ=0.5(先验中位)/se=None。
    网格搜索 θ 使对数似然最大（确定性、无随机、无外部依赖）。
    """
    n = len(responses)
    if n == 0:
        return {"theta": 0.5, "se": None, "n": 0}

    # 全对/全错的边界：MLE 会跑到 ±∞，收敛到 [0,1] 端点（加轻微收缩防极端）
    grid = [i / 200.0 for i in range(201)]  # θ ∈ [0,1] 步长 0.005
    best_theta, best_ll = 0.5, -math.inf
    for th in grid:
        ll = 0.0
        for b, correct in responses:
            p = min(max(_p_correct(th, b, scale), 1e-6), 1 - 1e-6)
            ll += math.log(p) if correct else math.log(1 - p)
        if ll > best_ll:
            best_ll, best_theta = ll, th

    # Fisher 信息 I(θ)=scale²·Σ p(1−p) → SE=1/sqrt(I)（logit 单位，再折回 [0,1] 尺度）
    info = sum(
        (scale**2)
        * _p_correct(best_theta, b, scale)
        * (1 - _p_correct(best_theta, b, scale))
        for b, _ in responses
    )
    se = round(1.0 / math.sqrt(info) / scale, 4) if info > 0 else None
    return {"theta": round(best_theta, 4), "se": se, "n": n}


def next_item_difficulty(theta: float) -> float:
    """CAT 选下一题：难度就近取 θ（Rasch 下 b=θ 时信息量最大、成功率≈50%）。
    实际投放可上移到 70–85% 成功带（见 learner_model.get_zpd_band）。"""
    return round(min(max(theta, 0.0), 1.0), 4)


__all__ = ["estimate_ability", "next_item_difficulty"]
