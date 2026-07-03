"""实验 1：BKT+FSRS 内核合成回归（判别力基线）。

选择说明：直接调 oskill.cognitive_state.cognitive_update（纯算法回放），
不走 services.cognitive_service.process_interaction 的 DB 全链路——
两者算法路径完全相同（服务层只是加持久化/快照/努力收益记账），
纯回放更快且不触碰任何数据库；集中练习去抖阈值 20h 与生产一致。

用法（api 容器内）：python scripts/moat_eval/exp1_kernel_auc.py
CI 守卫（快速档）：tests/test_moat_guard.py 调 run_exp1(n_students=60, n_study_days=14)。
"""

from __future__ import annotations

import json

import numpy as np

from common import (
    N_STUDENTS,
    N_STUDY_DAYS,
    SEED,
    auc,
    default_priors_lookup,
    generate_population,
    logloss,
    replay_population,
)


def run_exp1(
    seed: int = SEED,
    n_students: int = N_STUDENTS,
    n_study_days: int = N_STUDY_DAYS,
) -> dict:
    """生成群体→内核回放→指标，返回结果 dict（纯计算，不碰任何数据库）。"""
    population = generate_population(
        seed, n_students=n_students, n_study_days=n_study_days
    )
    n_events = sum(len(ev) for ev in population)

    preds = replay_population(population, default_priors_lookup(), fsrs_params=None)
    p = np.array([x[0] for x in preds])
    y = np.array([x[1] for x in preds])
    attempt = np.array([x[2] for x in preds])

    warm = attempt >= 1  # 该 (student,kc) 的第 2 次及以后作答（先验冷启动之外）
    return {
        "seed": seed,
        "n_students": len(population),
        "n_events": n_events,
        "min_events_per_student": min(len(e) for e in population),
        "overall": {"auc": round(auc(y, p), 3), "logloss": round(logloss(y, p), 3)},
        "warm_only": {
            "n": int(warm.sum()),
            "auc": round(auc(y[warm], p[warm]), 3),
            "logloss": round(logloss(y[warm], p[warm]), 3),
        },
        "base_rate_correct": round(float(y.mean()), 3),
        "gate_auc_ge_0.65": bool(auc(y, p) >= 0.65),
    }


def main() -> None:
    result = run_exp1()
    print(
        f"students={result['n_students']}  events={result['n_events']}  "
        f"min/student={result['min_events_per_student']}"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
