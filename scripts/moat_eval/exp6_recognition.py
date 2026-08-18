"""实验 6：recognition 识别维度独立验证（GH-2，M-G §4.5）。

动机（outputs/GAP-REVIEW-20260817.md P3-3）：moat_eval exp1-5 从未测过识别维度。
M-G 契约：每个 KC 维护 p_mastery（会不会做）与 p_recognition（混合情境认不认得
出该用它）；单 KC 专项只升 mastery，交错混合才训练 recognition。本实验在显式
双维度真值世界上验证三件事：

1. **判别增益**：混合情境预测用 pr×P(mixed|mastery)+(1-pr)×guess 是否比只用
   mastery 预测的 AUC 高（识别维度必须提供 mastery 之外的信息，否则该维度
   无存在价值）。
2. **惰性知识捕获**：只做专项练习的群体（真值 recognition 低）在训练后的
   混合迁移测试中错误率更高，且内核 p_recognition 应显著低于交错训练群体。
3. **方向正确**：交错做对 → p_recognition 升；交错做错 → 降（契约方向性回归）。

真值世界（与内核结构刻意不同源，防乐观偏差）：
- 每 (student, kc)：mastery ∈ {0,1}（学会与否），recog ∈ [0,1]（混合情境识别概率）。
- 专项作答（单 KC）：正确率 = mastery·(1-slip) + (1-mastery)·guess，不测识别。
- 混合作答：先以概率 recog 识别成功；识别失败 → 按 guess 蒙；识别成功 → 按专项正确率。
- 学习转移（与内核契约同向、但动力学刻意不同源，防乐观偏差）：
  答错未掌握 → 以 learn 概率学会；交错做对=成功识别→recog 以 recog_learn
  向 1 逼近（真值线性逼近，内核用 p_transit 递推）；交错做错=惰性知识→
  recog 以 recog_forget 乘性衰减（速率与内核 p_transit 不同源）。
- 训练期后追加纯混合迁移测试（每生 n_test 题，真值冻结不再学习）：
  惰性知识只能在迁移测试里干净地测出——训练期内交错型学生的混合事件
  集中在早期低 recog 阶段，会把组间差异稀释掉。

用法：python scripts/moat_eval/exp6_recognition.py
CI 守卫（快速档）：tests/test_recognition_guard.py 调 run_exp6(n_students=60)。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from common import auc, logloss  # noqa: E402

SEED = 42
N_STUDENTS = 150
N_KCS = 8
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

_PRIOR = {"p_init": 0.2, "p_transit": 0.2, "p_guess": 0.15, "p_slip": 0.12}


@dataclass
class Ev:
    kc_idx: int
    interleaved: bool
    correct: bool
    t: datetime
    is_test: bool = False  # 迁移测试事件：只测量、不学习


def generate_world(
    seed: int,
    n_students: int,
    n_kcs: int = N_KCS,
    n_days: int = 20,
    n_test: int = 6,
) -> tuple[list[list[Ev]], dict]:
    """生成双维度真值世界。返回 (events_by_student, truth)。

    前一半学生为"专项型"（80% 专项作答），后一半为"交错型"（80% 混合作答），
    制造惰性知识对照组。训练期后每生追加 n_test 道纯混合迁移测试（真值冻结）。
    """
    rng = np.random.default_rng(seed)
    population: list[list[Ev]] = []
    truth: dict[tuple[int, int], dict] = {}

    for s in range(n_students):
        interleaved_style = s >= n_students // 2  # 后半=交错型学生
        for k in range(n_kcs):
            truth[(s, k)] = {
                "mastery": bool(rng.random() < 0.25),
                "recog": float(rng.uniform(0.1, 0.3)),
                "learn": float(rng.uniform(0.1, 0.4)),
                "recog_learn": float(rng.uniform(0.15, 0.35)),
                "recog_forget": float(rng.uniform(0.05, 0.12)),
            }
        slip = float(rng.uniform(0.05, 0.15))
        guess = 0.2
        events: list[Ev] = []
        for day in range(n_days):
            for j in range(int(rng.integers(2, 4))):
                k = int(rng.integers(0, n_kcs))
                interleaved = bool(
                    rng.random() < (0.8 if interleaved_style else 0.2)
                )
                tr = truth[(s, k)]
                if interleaved:
                    recognized = bool(rng.random() < tr["recog"])
                    if not recognized:
                        correct = bool(rng.random() < guess)
                    else:
                        p = (1.0 - slip) if tr["mastery"] else guess
                        correct = bool(rng.random() < p)
                    # 契约同向的识别学习：交错做对=成功识别→升；做错=惰性知识→降。
                    # 动力学与内核不同源（真值：做对线性逼近/做错乘性衰减；
                    # 内核：p_transit 递推，两分支共用同一速率）。
                    if correct:
                        tr["recog"] = min(
                            0.97, tr["recog"] + (1.0 - tr["recog"]) * tr["recog_learn"]
                        )
                    else:
                        tr["recog"] = max(
                            0.03, tr["recog"] * (1.0 - tr["recog_forget"])
                        )
                else:
                    p = (1.0 - slip) if tr["mastery"] else guess
                    correct = bool(rng.random() < p)
                if not tr["mastery"] and not correct:
                    if rng.random() < tr["learn"]:
                        tr["mastery"] = True
                events.append(
                    Ev(
                        kc_idx=k,
                        interleaved=interleaved,
                        correct=correct,
                        t=T0 + timedelta(days=day, hours=j),
                    )
                )
        # 迁移测试：纯混合情境，真值冻结（不再学习），干净测量惰性知识。
        for j in range(n_test):
            k = int(rng.integers(0, n_kcs))
            tr = truth[(s, k)]
            recognized = bool(rng.random() < tr["recog"])
            if not recognized:
                correct = bool(rng.random() < guess)
            else:
                p = (1.0 - slip) if tr["mastery"] else guess
                correct = bool(rng.random() < p)
            events.append(
                Ev(
                    kc_idx=k,
                    interleaved=True,
                    correct=correct,
                    t=T0 + timedelta(days=n_days, hours=j),
                    is_test=True,
                )
            )
        population.append(events)
    return population, truth


def replay_world(population: list[list[Ev]]) -> dict:
    """内核回放：返回迁移测试预测序列 + 终态 recognition（按学生风格分组）。

    迁移测试事件只测量不学习（跳过 cognitive_update），保持与真值冻结同构。
    """
    from obase.cognitive_types import KCState, fsrs_new_card, new_state_from_prior
    from oprim.bkt import predict_correct
    from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update

    # 迁移测试预测：(pred_mastery_only, pred_with_recognition, y)
    mixed_preds: list[tuple[float, float, int]] = []
    final_recog: dict[str, list[float]] = {"focused": [], "interleaved": []}

    for s_idx, events in enumerate(population):
        style = "interleaved" if s_idx >= len(population) // 2 else "focused"
        states: dict[int, KCState] = {}
        cards: dict[int, dict] = {}
        for ev in events:
            if ev.kc_idx not in states:
                states[ev.kc_idx] = new_state_from_prior(
                    kc_id=f"kc{ev.kc_idx}", prior=dict(_PRIOR)
                )
                cards[ev.kc_idx] = fsrs_new_card()
            state, card = states[ev.kc_idx], cards[ev.kc_idx]
            if ev.is_test:
                p_m = float(
                    predict_correct(state=state, retrievability=1.0, difficulty=None)
                )
                pr = state.p_recognition
                if pr is None:
                    pr = state.p_recognition_init or 0.20
                # 混合情境全概率分解：识别成功→按 mastery 作答；识别失败→蒙 guess。
                # 不能直接 p_m×pr——那会把"识别失败仍可能蒙对"的 guess 项压到 0，
                # 系统性低估低识别群体、同时损害排序与校准。
                p_mix = float(pr) * p_m + (1.0 - float(pr)) * state.p_guess
                mixed_preds.append((p_m, p_mix, int(ev.correct)))
                continue  # 测试事件不学习
            res = cognitive_update(
                input=CognitiveUpdateInput(
                    state=state,
                    card_dict=card,
                    is_correct=ev.correct,
                    is_interleaved=ev.interleaved,
                    difficulty=None,
                    now=ev.t,
                    min_review_interval_hours=0.0,
                )
            )
            cards[ev.kc_idx] = res.card_dict
        for k, st in states.items():
            pr = st.p_recognition
            if pr is not None:
                final_recog[style].append(float(pr))
    return {"mixed_preds": mixed_preds, "final_recog": final_recog}


def run_exp6(seed: int = SEED, n_students: int = N_STUDENTS) -> dict:
    population, truth = generate_world(seed, n_students)
    r = replay_world(population)
    mp = r["mixed_preds"]
    p_m = np.array([x[0] for x in mp])
    p_r = np.array([x[1] for x in mp])
    y = np.array([x[2] for x in mp])

    auc_m = auc(y, p_m)
    auc_r = auc(y, p_r)

    fr = r["final_recog"]
    focused = np.array(fr["focused"]) if fr["focused"] else np.array([np.nan])
    interleaved = np.array(fr["interleaved"]) if fr["interleaved"] else np.array(
        [np.nan]
    )

    # 惰性知识：专项型 vs 交错型在迁移测试中的真实错误率
    mixed_err: dict[str, list[bool]] = {"focused": [], "interleaved": []}
    for s_idx, events in enumerate(population):
        style = "interleaved" if s_idx >= len(population) // 2 else "focused"
        for ev in events:
            if ev.is_test:
                mixed_err[style].append(ev.correct)
    err_f = 1.0 - (sum(mixed_err["focused"]) / max(1, len(mixed_err["focused"])))
    err_i = 1.0 - (sum(mixed_err["interleaved"]) / max(1, len(mixed_err["interleaved"])))

    return {
        "seed": seed,
        "n_students": n_students,
        "n_mixed_events": int(len(y)),
        "mixed_auc_mastery_only": round(auc_m, 3),
        "mixed_auc_with_recognition": round(auc_r, 3),
        "recognition_gain_auc": round(auc_r - auc_m, 3),
        "gain_positive": bool(auc_r > auc_m),
        "final_recog_focused_mean": round(float(np.nanmean(focused)), 3),
        "final_recog_interleaved_mean": round(float(np.nanmean(interleaved)), 3),
        "inert_knowledge_captured": bool(
            np.nanmean(interleaved) > np.nanmean(focused)
        ),
        "mixed_error_rate_focused": round(err_f, 3),
        "mixed_error_rate_interleaved": round(err_i, 3),
        "logloss_mastery_only": round(logloss(y, p_m), 3),
        "logloss_with_recognition": round(logloss(y, p_r), 3),
    }


def main() -> None:
    result = run_exp6()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
