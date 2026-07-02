"""实验 2：数据飞轮增益——BKT 先验校准 + FSRS 权重拟合，校准前后对比。

流程：
1. 同一合成群体（与实验 1 完全相同，seed=42），按学生时间序对半切分。
2. 前半数据灌入 DATABASE_URL 指向的库（必须是 mneme_moat_eval，脚本会校验，
   防止误灌 dev 库）的 users / bkt_priors / interaction_events（真实字段）。
3. 跑 services.calibration_service.calibrate_bkt_priors（写 calibrated_from_n）
   与 services.fsrs_optimize_service 的权重择优/拟合（global cohort）。
4. 后半数据上对比 4 个 arm 的预测 AUC / log-loss：
   default | +校准先验 | +拟合FSRS权重 | 两者都用。
   （回放从 t=0 开始暖机，但只对后半事件计分；校准只见过前半 → 无标签泄漏。）

用法（api 容器内）：
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/mneme_moat_eval \
  MOAT_FIT_MAXITER=3 python scripts/moat_eval/exp2_flywheel.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import numpy as np

from common import (
    _REPO,
    SEED,
    auc,
    default_priors_lookup,
    generate_population,
    logloss,
    replay_population,
)

REQUIRED_DB = "mneme_moat_eval"


def _split_idx(n: int) -> int:
    return n // 2


async def prepare_db(Session, population) -> None:
    """清空实验表 → seed 先验 → 建学生 → 灌前半 interaction_events。"""
    import importlib.util

    from sqlalchemy import text

    from services.models import InteractionEvent, User

    # seed_priors 脚本复用（单源：不复制展开逻辑）
    spec = importlib.util.spec_from_file_location(
        "seed_priors", str(_REPO / "scripts" / "seed_priors.py")
    )
    seed_priors = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_priors)

    async with Session() as db:
        await db.execute(
            text(
                "TRUNCATE interaction_events, fsrs_weights, bkt_priors RESTART IDENTITY CASCADE"
            )
        )
        await db.execute(text("DELETE FROM users"))
        await db.commit()

    await seed_priors.seed_bkt_priors()

    async with Session() as db:
        for s in range(len(population)):
            db.add(
                User(
                    id=uuid.UUID(int=s + 1),
                    phone=f"139{s:08d}",
                    role="student",
                    name=f"synth-{s:03d}",
                    grade="高一",
                )
            )
        await db.flush()
        n_rows = 0
        for s, events in enumerate(population):
            half = _split_idx(len(events))
            for ev in events[:half]:
                db.add(
                    InteractionEvent(
                        id=uuid.uuid4(),
                        student_id=uuid.UUID(int=s + 1),
                        knowledge_point=ev.kc_id,
                        source="paper",
                        is_correct=ev.correct,
                        fsrs_rating=3
                        if ev.correct
                        else 1,  # Good / Again（合成无吃力/秒杀信号）
                        item_difficulty=round(ev.difficulty, 4),
                        occurred_at=ev.t,
                    )
                )
                n_rows += 1
        await db.commit()
    print(f"[prepare] inserted first-half events: {n_rows}")


async def run_flywheel(Session) -> tuple[dict, tuple | None, dict]:
    """校准 + 权重拟合，返回 (校准统计, 拟合出的权重|None, 权重统计)。"""
    from fsrs import Scheduler

    from services.calibration_service import calibrate_bkt_priors
    from services.fsrs_optimize_service import (
        evaluate_weights,
        fit_weights,
        load_cohort_weights,
        propose_candidates,
        reconstruct_review_logs,
        select_best_weights,
    )

    async with Session() as db:
        cal_stats = await calibrate_bkt_priors(db)
        await db.commit()
    print(f"[calibrate] {cal_stats}")

    async with Session() as db:
        default_params = list(Scheduler().parameters)
        candidates = [None] + propose_candidates(default_params, n=16, seed=SEED)
        t0 = time.time()
        sel = await select_best_weights(db, candidates, cohort="global")
        print(f"[fsrs-select] {sel}  ({time.time() - t0:.1f}s)")

        # 可选：scipy Powell 导数无关拟合（服务自带；MOAT_FIT_MAXITER=0 跳过）
        maxiter = int(os.environ.get("MOAT_FIT_MAXITER", "0"))
        if maxiter > 0:
            seqs = await reconstruct_review_logs(db)
            t0 = time.time()
            best, best_loss, default_loss = fit_weights(seqs, maxiter=maxiter)
            print(
                f"[fsrs-fit] powell maxiter={maxiter} default_ll={default_loss:.4f} "
                f"fit_ll={best_loss:.4f} improved={best is not None} "
                f"({time.time() - t0:.1f}s)"
            )
            # 拟合若优于择优结果则覆盖存储
            if best is not None and best_loss < sel.get("best_logloss", float("inf")):
                from services.fsrs_optimize_service import _store_weights

                n = evaluate_weights(seqs, None)[1]
                await _store_weights(db, "global", best, best_loss, n)
        await db.commit()
        stored = await load_cohort_weights(db, "global")
        weight_stats = dict(sel)

    return cal_stats, stored, weight_stats


async def read_calibrated_priors(Session) -> dict[tuple[str, str], dict]:
    from sqlalchemy import select

    from services.models import BKTPrior

    out: dict[tuple[str, str], dict] = {}
    async with Session() as db:
        rows = (await db.execute(select(BKTPrior))).scalars().all()
        for r in rows:
            out[(r.knowledge_point, r.question_type)] = {
                "p_init": r.p_init,
                "p_transit": r.p_transit,
                "p_guess": r.p_guess,
                "p_slip": r.p_slip,
            }
    return out


def score_arm(population, priors, fsrs_params) -> dict:
    """全程回放（暖机），只对每个学生后半事件计分。"""
    preds = replay_population(population, priors, fsrs_params=fsrs_params)
    # replay 按学生顺序展平 → 重建每学生的切分掩码
    mask, y, p = [], [], []
    i = 0
    for events in population:
        half = _split_idx(len(events))
        for j in range(len(events)):
            if j >= half:
                p.append(preds[i][0])
                y.append(preds[i][1])
            i += 1
    y_arr, p_arr = np.array(y), np.array(p)
    return {
        "n": len(y_arr),
        "auc": round(auc(y_arr, p_arr), 3),
        "logloss": round(logloss(y_arr, p_arr), 3),
    }


async def main() -> None:
    from obase.config import settings

    if REQUIRED_DB not in settings.DATABASE_URL:
        raise SystemExit(
            f"安全校验失败：DATABASE_URL 必须指向 {REQUIRED_DB}（隔离实验库），"
            f"当前 = {settings.DATABASE_URL}"
        )

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    population = generate_population(SEED)
    await prepare_db(Session, population)
    cal_stats, fitted_weights, weight_stats = await run_flywheel(Session)
    calibrated_priors = await read_calibrated_priors(Session)
    await engine.dispose()

    default_priors = default_priors_lookup()
    arms = {
        "default": score_arm(population, default_priors, None),
        "calibrated_priors_only": score_arm(population, calibrated_priors, None),
        "fitted_fsrs_only": score_arm(population, default_priors, fitted_weights),
        "calibrated_plus_fitted": score_arm(
            population, calibrated_priors, fitted_weights
        ),
    }
    result = {
        "seed": SEED,
        "calibration": cal_stats,
        "fsrs_weight_selection": weight_stats,
        "fsrs_weights_stored": fitted_weights is not None,
        "eval_arms_second_half": arms,
        "delta_auc_both_vs_default": round(
            arms["calibrated_plus_fitted"]["auc"] - arms["default"]["auc"], 3
        ),
        "delta_logloss_both_vs_default": round(
            arms["calibrated_plus_fitted"]["logloss"] - arms["default"]["logloss"], 3
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
