"""情感感知（教育理念 08·D'Mello & Graesser）。纯函数，确定性启发式 v1。

无摄像头/生物特征——只用**行为信号代理**估计学习情感态：挫败(frustrated)/脱离(disengaged)/
心流(flow)/中性(neutral)，并给自适应教学建议。阈值为 v1 经验值，后续用真实数据校准。
合规：不采集任何生物特征。
"""

from __future__ import annotations


def affect_estimate(
    *,
    consecutive_wrong: int = 0,
    reveal_rate: float = 0.0,
    give_up_rate: float = 0.0,
    recent_correct_streak: int = 0,
    fast_correct: bool = False,
) -> dict:
    """行为信号 → {state, adaptation}。

    - ``frustrated`` 连错≥3 或 放弃率高 → 降难度+鼓励+补救阶梯
    - ``disengaged`` 看答案率高 / 频繁放弃 → 换题型/交错提神+缩短目标
    - ``flow``       连对且快 → 加挑战(desirable difficulty)
    - ``neutral``    其余
    """
    if consecutive_wrong >= 3 or give_up_rate >= 0.5:
        return {
            "state": "frustrated",
            "adaptation": "lower_difficulty_encourage_scaffold",
        }
    if reveal_rate >= 0.5 or give_up_rate >= 0.3:
        return {
            "state": "disengaged",
            "adaptation": "switch_type_interleave_shorten_goal",
        }
    if recent_correct_streak >= 5 and fast_correct:
        return {"state": "flow", "adaptation": "raise_challenge"}
    return {"state": "neutral", "adaptation": "keep"}


__all__ = ["affect_estimate"]
