"""实验 1：BKT+FSRS 内核合成回归（判别力基线）。

选择说明：直接调 oskill.cognitive_state.cognitive_update（纯算法回放），
不走 services.cognitive_service.process_interaction 的 DB 全链路——
两者算法路径完全相同（服务层只是加持久化/快照/努力收益记账），
纯回放更快且不触碰任何数据库；集中练习去抖阈值 20h 与生产一致。

用法（api 容器内）：python scripts/moat_eval/exp1_kernel_auc.py
"""

from __future__ import annotations

import json

import numpy as np

from common import (
    SEED,
    auc,
    default_priors_lookup,
    generate_population,
    logloss,
    replay_population,
)


def main() -> None:
    population = generate_population(SEED)
    n_events = sum(len(ev) for ev in population)
    print(
        f"students={len(population)}  events={n_events}  "
        f"min/student={min(len(e) for e in population)}"
    )

    preds = replay_population(population, default_priors_lookup(), fsrs_params=None)
    p = np.array([x[0] for x in preds])
    y = np.array([x[1] for x in preds])
    attempt = np.array([x[2] for x in preds])

    warm = attempt >= 1  # 该 (student,kc) 的第 2 次及以后作答（先验冷启动之外）
    result = {
        "seed": SEED,
        "n_students": len(population),
        "n_events": n_events,
        "overall": {"auc": round(auc(y, p), 3), "logloss": round(logloss(y, p), 3)},
        "warm_only": {
            "n": int(warm.sum()),
            "auc": round(auc(y[warm], p[warm]), 3),
            "logloss": round(logloss(y[warm], p[warm]), 3),
        },
        "base_rate_correct": round(float(y.mean()), 3),
        "gate_auc_ge_0.65": bool(auc(y, p) >= 0.65),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
