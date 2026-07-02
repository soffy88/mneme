"""实验 4：FIRe-lite 前置信用回写（M-H §4.8）——接线决策仿真。

带前置图的 KC 集合：N_TRIPLES 条独立三层链 kc0 ← kc1 ← kc2（kc2 综合、kc1 中间、
kc0 根前置；边均视为 verified）。真值记忆沿用 exp3 的 ExpTruth（指数遗忘+间隔效应，
刻意与 FSRS 幂律不同形）。

世界真值（"综合题成功确实部分刷新前置记忆"的强度 ρ，保守设定）：
- FIRe 世界（ρ=0.3 / 0.5）：某 KC 复习成功时，其**直接**前置在真值里获得
  ρ 折扣的隐式刷新：S ← S×(1+ρ·G·(1-R_true))，recency 按 ρ 部分前移
  （last ← last + ρ·(t-last)）。不级联（只直接前置，与实现一致）。
- 对抗世界（ρ=0）：前置完全不被刷新——FIRe 假设不成立，量测 FIRe 的伤害上限。

两组调度（每个世界各跑一遍，同 seed 同初始群体）：
- no_fire：纯 FSRS due 驱动（内核 cognitive_update，20h 去抖，与生产一致）。
- fire   ：同上 + 综合/中间 KC 复习成功后调 oskill.fire_propagate
           （κ0=0.5, τ=0.3，真实内核代码），仅顺延直接前置的 due。

流程：历史期（负天数）建立前置的 BKT P(L) 与 FSRS 调度 → 第 1~30 天每日队列
（due≤当日即复习，综合层先处理）→ 第 30 天量测保留率 E[R_true] 与总复习次数。

决策规则（TASKS T.5）：FIRe 世界复习量压缩 ≥10% 且对抗世界保留率损失 ≤2pp
→ 允许接线（默认开）；否则默认关。

用法（api 容器内）：python scripts/moat_eval/exp4_fire.py
"""

from __future__ import annotations

import json
import math
import os
from datetime import timedelta

import numpy as np

from common import SEED, T0

N_TRIPLES = int(os.environ.get("MOAT_TRIPLES", "1500"))
WINDOW_DAYS = 30.0
GAIN = 3.0  # 间隔效应增益（同 exp3 ExpTruth）
KAPPA0 = 0.5
TAU = 0.3

# 三层链的历史练习日程（负数=窗口开始前）：前置学得更早、练得更多。
HISTORY = {
    "kc0": [-12.0, -8.0, -4.0],
    "kc1": [-8.0, -4.0],
    "kc2": [0.0],
}
PREREQ_OF = {"kc2": "kc1", "kc1": "kc0", "kc0": None}
PRIOR = {"p_init": 0.3, "p_transit": 0.2, "p_guess": 0.15, "p_slip": 0.1}


# ── 真值：exp3 的 ExpTruth + 隐式刷新 ─────────────────────────────
def new_truth_item(rng: np.random.Generator, t_first: float) -> dict:
    s0 = float(np.exp(rng.normal(np.log(1.5), 0.6)))
    return {"S": s0, "S0": s0, "last": t_first}


def truth_review(item: dict, t: float, rng: np.random.Generator) -> bool:
    r_true = math.exp(-(t - item["last"]) / item["S"])
    recalled = bool(rng.random() < r_true)
    if recalled:
        item["S"] = item["S"] * (1.0 + GAIN * (1.0 - r_true))
    else:
        item["S"] = max(item["S0"], 0.4 * item["S"])
    item["last"] = t
    return recalled


def implicit_refresh(item: dict, t: float, rho: float) -> None:
    """综合题成功对直接前置的真值隐式刷新（ρ 折扣；ρ=0 即对抗世界，无操作）。"""
    if rho <= 0.0:
        return
    r_true = math.exp(-(t - item["last"]) / item["S"])
    item["S"] = item["S"] * (1.0 + rho * GAIN * (1.0 - r_true))
    item["last"] = item["last"] + rho * (t - item["last"])


def truth_retention(item: dict, at_day: float = WINDOW_DAYS) -> float:
    return math.exp(-(at_day - item["last"]) / item["S"])


# ── 调度侧（真实内核）────────────────────────────────────────────
def _due_day(card: dict) -> float | None:
    from datetime import datetime

    due = card.get("due")
    if not due:
        return None
    due_dt = datetime.fromisoformat(due) if isinstance(due, str) else due
    return (due_dt - T0).total_seconds() / 86400.0


def run_arm(rho: float, fire_on: bool) -> dict:
    """跑一个 (世界 ρ, FIRe 开关) 组合，返回保留率与复习量。"""
    import random

    from obase.cognitive_types import fsrs_new_card, new_state_from_prior
    from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update
    from oskill.fire_propagate import FirePrereq, fire_propagate

    rng = np.random.default_rng(SEED)
    random.seed(SEED)  # py-fsrs 间隔 fuzz 走 stdlib random，必须播种

    kcs = list(HISTORY.keys())
    retention: dict[str, list[float]] = {k: [] for k in kcs}
    n_reviews = {k: 0 for k in kcs}
    n_fire_writes = 0

    for _ in range(N_TRIPLES):
        truth = {k: new_truth_item(rng, HISTORY[k][0]) for k in kcs}
        states = {k: new_state_from_prior(kc_id=k, prior=dict(PRIOR)) for k in kcs}
        cards = {k: fsrs_new_card() for k in kcs}

        def review(kc: str, t: float) -> None:
            nonlocal n_fire_writes
            recalled = truth_review(truth[kc], t, rng)
            res = cognitive_update(
                input=CognitiveUpdateInput(
                    state=states[kc],
                    card_dict=cards[kc],
                    is_correct=recalled,
                    now=T0 + timedelta(days=t),
                    min_review_interval_hours=20.0,
                )
            )
            cards[kc] = res.card_dict
            p = PREREQ_OF[kc]
            if recalled and p is not None:
                # 世界动力学：真值隐式刷新（与调度组无关，两组一致）
                implicit_refresh(truth[p], t, rho)
                if fire_on and res.schedule_advanced:
                    outcomes = fire_propagate(
                        trigger_kc_id=kc,
                        prereqs=[
                            FirePrereq(
                                kc_id=p,
                                p_mastery=states[p].current(),
                                card_dict=cards[p],
                            )
                        ],
                        now=T0 + timedelta(days=t),
                        kappa0=KAPPA0,
                        tau=TAU,
                    )
                    if outcomes and outcomes[0].new_due is not None:
                        cards[p] = {**cards[p], "due": outcomes[0].new_due}
                        n_fire_writes += 1

        # 历史期：按固定日程练习（建立 P(L) 与 FSRS 调度）
        for t_hist in sorted({t for ts in HISTORY.values() for t in ts}):
            for kc in ("kc2", "kc1", "kc0"):  # 综合层先处理（与主窗口一致）
                if t_hist in HISTORY[kc]:
                    review(kc, t_hist)

        # 主窗口：第 1~30 天每日到期队列，综合层先处理
        for day in range(1, int(WINDOW_DAYS) + 1):
            t = float(day)
            for kc in ("kc2", "kc1", "kc0"):
                dd = _due_day(cards[kc])
                if dd is not None and dd <= t:
                    review(kc, t)
                    n_reviews[kc] += 1

        for kc in kcs:
            retention[kc].append(truth_retention(truth[kc]))

    total_reviews = sum(n_reviews.values())
    all_r = [r for kc in kcs for r in retention[kc]]
    return {
        "retention_day30": round(float(np.mean(all_r)), 4),
        "retention_by_kc": {kc: round(float(np.mean(retention[kc])), 4) for kc in kcs},
        "reviews_per_triple": round(total_reviews / N_TRIPLES, 3),
        "reviews_by_kc": {kc: round(n_reviews[kc] / N_TRIPLES, 3) for kc in kcs},
        "fire_writes_per_triple": round(n_fire_writes / N_TRIPLES, 3),
    }


def main() -> None:
    worlds = [
        ("fire_world_rho0.3", 0.3),
        ("fire_world_rho0.5", 0.5),
        ("adversarial_rho0", 0.0),
    ]
    out: dict = {
        "seed": SEED,
        "n_triples": N_TRIPLES,
        "window_days": WINDOW_DAYS,
        "kappa0": KAPPA0,
        "tau": TAU,
        "worlds": {},
    }
    for name, rho in worlds:
        base = run_arm(rho, fire_on=False)
        fire = run_arm(rho, fire_on=True)
        compression = 1.0 - fire["reviews_per_triple"] / base["reviews_per_triple"]
        out["worlds"][name] = {
            "rho": rho,
            "no_fire": base,
            "fire": fire,
            "review_compression": round(compression, 4),
            "retention_delta_pp": round(
                (fire["retention_day30"] - base["retention_day30"]) * 100.0, 2
            ),
        }

    w03 = out["worlds"]["fire_world_rho0.3"]
    w05 = out["worlds"]["fire_world_rho0.5"]
    adv = out["worlds"]["adversarial_rho0"]
    decision_ok = (
        min(w03["review_compression"], w05["review_compression"]) >= 0.10
        and adv["retention_delta_pp"] >= -2.0
    )
    out["decision"] = {
        "rule": "FIRe 世界压缩≥10% 且对抗世界保留率损失≤2pp → 接线（默认开）",
        "min_fire_world_compression": min(
            w03["review_compression"], w05["review_compression"]
        ),
        "adversarial_retention_loss_pp": -adv["retention_delta_pp"],
        "wire_default_on": decision_ok,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
