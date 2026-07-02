"""实验 3：调度质量——FSRS 间隔调度 vs 固定间隔(每3天) vs 不复习。

两种真值记忆模型（MOAT_TRUTH=exp|fsrs，默认 exp）：

A) exp（对抗形，刻意与 FSRS 幂律不同形）：
- 每个记忆项 i：真稳定性 S_true，R_true(Δt) = exp(-Δt / S_true)。
- 复习按 R_true 采样是否想起：
  - 想起：间隔效应 S_true ← S_true × (1 + G·(1 - R_true))——越"艰难的成功提取"
    增益越大（提取难度是可取难度）。
  - 想不起：看答案重学，S_true ← max(S0, 0.4·S_true)（有节省但大幅回落）。
- 复习无论成败都刷新"上次接触时刻"。

B) fsrs（同族形）：真值记忆本身就是一张 FSRS 卡片，但真值权重按项目
   在默认权重上 ±25% 抖动（调度器只用默认权重，不知道真值权重）。
   用于展示"真实遗忘曲线属 FSRS 族时"的调度收益上限——与 A 对照说明
   结论对真值遗忘动力学形状敏感。

三组同预算（每项最多 B 次复习，30 天窗口）：
- fsrs_schedule：按 FSRS 卡片 due 日复习（表现→Rating→下一个 due）。
  复习以"天"为粒度（产品是每日复习队列 + 20h 集中练习去抖，
  cognitive_service._MASSED_PRACTICE_DEBOUNCE_HOURS），due 超出 30 天窗即停。
- fixed_3d：第 3,6,9,… 天复习（用满预算）。
- no_review：不复习。
第 30 天量测保留率 = E[R_true(day 30)]。

用法（api 容器内）：
  MOAT_TRUTH=exp  MOAT_BUDGET=5 MOAT_S0=1.5 python scripts/moat_eval/exp3_scheduling.py
  MOAT_TRUTH=fsrs MOAT_BUDGET=5 python scripts/moat_eval/exp3_scheduling.py
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta

import numpy as np

from common import SEED, T0

N_ITEMS = 3000  # 记忆项（学生×知识项展开）
BUDGET = int(os.environ.get("MOAT_BUDGET", "5"))  # 每项复习预算
WINDOW_DAYS = 30.0
GAIN = 3.0  # 间隔效应增益系数 G（exp 真值）
S0_MEDIAN = float(os.environ.get("MOAT_S0", "1.5"))  # 初始稳定性中位数（天）
TRUTH = os.environ.get("MOAT_TRUTH", "exp")  # exp | fsrs


# ── 真值模型 A：指数遗忘 + 间隔效应 ──────────────────────────────
class ExpTruth:
    name = "exp_decay_spacing"

    def new_item(self, rng: np.random.Generator) -> dict:
        s0 = float(np.exp(rng.normal(np.log(S0_MEDIAN), 0.6)))
        return {"S": s0, "S0": s0, "last": 0.0}

    def review_at(self, item: dict, t_day: float, rng: np.random.Generator) -> bool:
        r_true = math.exp(-(t_day - item["last"]) / item["S"])
        recalled = bool(rng.random() < r_true)
        if recalled:
            item["S"] = item["S"] * (1.0 + GAIN * (1.0 - r_true))
        else:
            item["S"] = max(item["S0"], 0.4 * item["S"])
        item["last"] = t_day
        return recalled

    def retention_day30(self, item: dict) -> float:
        return math.exp(-(WINDOW_DAYS - item["last"]) / item["S"])


# ── 真值模型 B：FSRS 族（真值权重抖动，调度器只知默认权重）─────────
class FsrsTruth:
    name = "fsrs_family_jittered"

    def __init__(self) -> None:
        from fsrs import Rating, Scheduler

        self._Rating = Rating
        self._default = list(Scheduler().parameters)

    def new_item(self, rng: np.random.Generator) -> dict:
        from fsrs.scheduler import LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS

        from obase.cognitive_types import fsrs_new_card
        from oprim.fsrs_engine import fsrs_review

        params = tuple(
            float(np.clip(p * (1.0 + float(rng.uniform(-0.25, 0.25))), lo, hi))
            for p, lo, hi in zip(
                self._default, LOWER_BOUNDS_PARAMETERS, UPPER_BOUNDS_PARAMETERS
            )
        )
        card = fsrs_review(
            card_dict=fsrs_new_card(),
            rating=self._Rating.Good,
            now=T0,
            parameters=params,
        )
        return {"card": card, "params": params, "last": 0.0}

    def review_at(self, item: dict, t_day: float, rng: np.random.Generator) -> bool:
        from oprim.fsrs_engine import fsrs_retrievability, fsrs_review

        now = T0 + timedelta(days=t_day)
        r_true = fsrs_retrievability(
            card_dict=item["card"], now=now, parameters=item["params"]
        )
        recalled = bool(rng.random() < r_true)
        rating = self._Rating.Good if recalled else self._Rating.Again
        item["card"] = fsrs_review(
            card_dict=item["card"], rating=rating, now=now, parameters=item["params"]
        )
        item["last"] = t_day
        return recalled

    def retention_day30(self, item: dict) -> float:
        from oprim.fsrs_engine import fsrs_retrievability

        return float(
            fsrs_retrievability(
                card_dict=item["card"],
                now=T0 + timedelta(days=WINDOW_DAYS),
                parameters=item["params"],
            )
        )


def _make_truth():
    return FsrsTruth() if TRUTH == "fsrs" else ExpTruth()


def run_none(rng: np.random.Generator) -> tuple[float, float]:
    truth = _make_truth()
    items = [truth.new_item(rng) for _ in range(N_ITEMS)]
    return float(np.mean([truth.retention_day30(it) for it in items])), 0.0


def run_fixed(rng: np.random.Generator, interval: float = 3.0) -> tuple[float, float]:
    truth = _make_truth()
    items = [truth.new_item(rng) for _ in range(N_ITEMS)]
    n_reviews = 0
    for it in items:
        for k in range(1, BUDGET + 1):
            t = k * interval
            if t >= WINDOW_DAYS:
                break
            truth.review_at(it, t, rng)
            n_reviews += 1
    return (
        float(np.mean([truth.retention_day30(it) for it in items])),
        n_reviews / len(items),
    )


def run_fsrs(rng: np.random.Generator) -> tuple[float, float]:
    from fsrs import Rating

    from obase.cognitive_types import fsrs_new_card
    from oprim.fsrs_engine import fsrs_review

    truth = _make_truth()
    items = [truth.new_item(rng) for _ in range(N_ITEMS)]
    n_reviews = 0
    for it in items:
        # day 0 学会：调度侧 FSRS 卡片（默认权重）做一次 Good 建立初始调度
        card = fsrs_review(card_dict=fsrs_new_card(), rating=Rating.Good, now=T0)
        for _ in range(BUDGET):
            due = card["due"]
            due_dt = datetime.fromisoformat(due) if isinstance(due, str) else due
            t = (due_dt - T0).total_seconds() / 86400.0
            # 复习以"天"为粒度：产品是每日复习队列 + 20h 集中练习去抖，
            # py-fsrs 分钟级 learning steps 的 due 并到次日执行。
            t = max(t, it["last"] + 1.0)
            if t >= WINDOW_DAYS:
                break
            recalled = truth.review_at(it, t, rng)
            rating = Rating.Good if recalled else Rating.Again
            card = fsrs_review(
                card_dict=card, rating=rating, now=T0 + timedelta(days=t)
            )
            n_reviews += 1
    return (
        float(np.mean([truth.retention_day30(it) for it in items])),
        n_reviews / len(items),
    )


def main() -> None:
    import random

    results = {}
    for name, fn in [
        ("fsrs_schedule", run_fsrs),
        ("fixed_3d", run_fixed),
        ("no_review", run_none),
    ]:
        rng = np.random.default_rng(SEED)  # 各组同 seed（同一初始真值群体）
        # py-fsrs 的间隔 fuzz 用 stdlib random（默认未播种）→ 必须播种保证可复现
        random.seed(SEED)
        retention, avg_reviews = fn(rng)
        results[name] = {
            "retention_day30": round(retention, 3),
            "avg_reviews_per_item": round(avg_reviews, 2),
        }
    out = {
        "seed": SEED,
        "truth_model": _make_truth().name,
        "n_items": N_ITEMS,
        "budget_reviews_per_item": BUDGET,
        "s0_median_days": S0_MEDIAN if TRUTH == "exp" else None,
        "window_days": WINDOW_DAYS,
        "groups": results,
        "fsrs_minus_fixed3d": round(
            results["fsrs_schedule"]["retention_day30"]
            - results["fixed_3d"]["retention_day30"],
            3,
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
