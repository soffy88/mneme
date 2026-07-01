"""JOL 校准指标（Brier score + 过度自信）。

确定性 oprim 原子操作：给定"作答前自评把握度"序列与"实际对错"序列，
算 Brier、平均把握、实际正确率、过度自信。此前内联在服务层 main.py，
违反"服务层不算确定性指标"，上移至 oprim。
"""
from __future__ import annotations

from typing import Optional, Sequence


def brier_calibration(*, predicted: Sequence[float], actual: Sequence[float]) -> dict:
    """预测把握度 vs 实际对错 → 校准指标。

    brier 越低越准；overconfidence>0=高估自己(努力错觉)，<0=低估自己。
    空输入返回全 None（n=0）。
    """
    n = len(predicted)
    if n == 0:
        return {"n": 0, "brier": None, "mean_predicted": None, "accuracy": None, "overconfidence": None}
    preds = [float(p) for p in predicted]
    actuals = [float(a) for a in actual]
    brier = sum((p - a) ** 2 for p, a in zip(preds, actuals)) / n
    mean_pred = sum(preds) / n
    acc = sum(actuals) / n
    return {
        "n": n,
        "brier": round(brier, 4),
        "mean_predicted": round(mean_pred, 4),
        "accuracy": round(acc, 4),
        "overconfidence": round(mean_pred - acc, 4),
    }


__all__ = ["brier_calibration"]
