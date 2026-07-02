"""moat_eval 共用件：合成学生群体生成 + 内核回放 + 指标。

全部随机数走固定 seed 的 numpy Generator，保证可复现。

真值生成模型（与内核 BKT 结构相似但参数独立采样，见 README 局限性说明）：
- 每个 (student, kc) 有隐藏二元知识状态 known ∈ {0,1}。
- known=1 时可提取性按指数遗忘 R_true = 0.5^(Δt/τ) 衰减（τ 为该生该 KC 半衰期）。
- 作答概率 p = R_eff·(1-slip) + (1-R_eff)·guess，R_eff = known·R_true；
  题目难度 b 在 logit 空间调制 slip/guess（与内核 _item_adjust 同形，乐观偏差之一）。
- 作答（含反馈）后：未掌握则以 learn_rate 概率转为掌握；成功的间隔提取使 τ 增长
  （间隔效应）；每次练习刷新"上次接触时间"。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── sys.path 引导：vendor 优先（与 services/__init__ 运行时注入一致）──
_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from data.guangdong_math_kc import KC_LIST  # noqa: E402

SEED = 42
N_STUDENTS = 200
KCS_PER_STUDENT = 6
MIN_EVENTS_PER_STUDENT = 50
HORIZON_DAYS = 120
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

# 与 scripts/seed_priors.py 的题型猜测率一致（默认先验的题型展开）
GUESS_RATES = {"choice": 0.25, "fill": 0.05, "solve": 0.02}

# 参与实验的 KC 池：取字典前 12 个（覆盖多模块，确定性选取）
KC_POOL = KC_LIST[:12]
KC_BY_ID = {kc["kc_id"]: kc for kc in KC_POOL}


@dataclass
class Event:
    student_idx: int
    kc_id: str
    qtype: str
    difficulty: float
    t: datetime  # 发生时刻
    correct: bool
    # 真值侧信息（仅诊断用，不进内核）
    known_before: bool = False
    r_true: float = 1.0


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _logit(x: float, eps: float = 1e-4) -> float:
    x = min(max(x, eps), 1.0 - eps)
    return math.log(x / (1.0 - x))


def _item_adjust_true(guess: float, slip: float, b: float) -> tuple[float, float]:
    """真值模型的难度调制（与内核 _item_adjust 同形——已在局限性中声明）。"""
    delta = b - 0.5
    return (_sigmoid(_logit(guess) - 1.0 * delta), _sigmoid(_logit(slip) + 1.0 * delta))


def generate_population(seed: int = SEED) -> list[list[Event]]:
    """生成合成学生群体，返回 events_by_student（每个学生按时间排序）。

    真值参数与种子先验系统性偏离（模拟"冷启动手设先验不准"的现实）：
    - 真 slip 均值 ~0.20（种子 ~0.08-0.14）→ 校准应能发现
    - 真学习率整体低于种子 p_transit
    - 真初始掌握 = sigmoid(能力 + logit(种子 p_init) - 0.3)
    """
    rng = np.random.default_rng(seed)
    population: list[list[Event]] = []

    for s in range(N_STUDENTS):
        ability = float(rng.normal(0.0, 1.0))
        speed = math.exp(0.4 * ability)  # 能力→学习速度
        slip_s = float(np.clip(rng.beta(2.5, 10.0) + 0.05, 0.02, 0.35))
        tau_s = float(np.exp(rng.normal(np.log(8.0), 0.5)))  # 遗忘半衰期(天) 中位 8

        kc_ids = list(
            rng.choice(
                [k["kc_id"] for k in KC_POOL], size=KCS_PER_STUDENT, replace=False
            )
        )
        truth: dict[str, dict] = {}
        for kc_id in kc_ids:
            seed_bkt = KC_BY_ID[kc_id]["bkt"]
            p0 = _sigmoid(ability + _logit(seed_bkt["p_init"]) - 0.3)
            truth[kc_id] = {
                "known": bool(rng.random() < p0),
                "learn": float(
                    np.clip(
                        seed_bkt["p_transit"]
                        * 0.6
                        * speed
                        * float(rng.uniform(0.6, 1.4)),
                        0.02,
                        0.6,
                    )
                ),
                "slip": slip_s,
                "tau": float(np.clip(tau_s * float(rng.uniform(0.7, 1.3)), 2.0, 60.0)),
                "last_touch": None,  # 天（浮点），None=尚未接触
            }

        # 学习日程：25 个随机学习日 × 每日 2-4 题 → 每人 50~100 次交互（≥50 有保证）
        events: list[Event] = []
        day_pool = [int(d) for d in rng.permutation(HORIZON_DAYS)]
        study_days = sorted(day_pool[:25])

        for day in study_days:
            n_q = int(rng.integers(2, 5))
            for j in range(n_q):
                kc_id = str(rng.choice(kc_ids))
                kc = KC_BY_ID[kc_id]
                qtype = str(rng.choice(kc["question_types"]))
                b = float(np.clip(rng.normal(0.5, 0.15), 0.05, 0.95))
                t_day = day + 0.5 + 0.05 * j  # 同日题间隔 ~72 分钟
                tr = truth[kc_id]

                guess_true = {"choice": 0.25, "fill": 0.06, "solve": 0.03}[qtype]
                g_adj, s_adj = _item_adjust_true(guess_true, tr["slip"], b)

                if tr["known"] and tr["last_touch"] is not None:
                    r_true = 0.5 ** ((t_day - tr["last_touch"]) / tr["tau"])
                elif tr["known"]:
                    r_true = 1.0
                else:
                    r_true = 0.0
                p_correct = r_true * (1.0 - s_adj) + (1.0 - r_true) * g_adj
                correct = bool(rng.random() < p_correct)

                events.append(
                    Event(
                        student_idx=s,
                        kc_id=kc_id,
                        qtype=qtype,
                        difficulty=b,
                        t=T0 + timedelta(days=t_day),
                        correct=correct,
                        known_before=tr["known"],
                        r_true=r_true,
                    )
                )

                # 真值状态转移（作答后有反馈）
                if not tr["known"]:
                    if rng.random() < tr["learn"]:
                        tr["known"] = True
                        tr["last_touch"] = t_day
                else:
                    if correct and r_true < 1.0:
                        # 间隔效应：越"艰难的成功提取"带来越大的 τ 增长
                        tr["tau"] = min(60.0, tr["tau"] * (1.0 + 0.6 * (1.0 - r_true)))
                    tr["last_touch"] = t_day

        events.sort(key=lambda e: e.t)
        population.append(events)
    return population


def default_priors_lookup() -> dict[tuple[str, str], dict]:
    """(kc_id, qtype) → 种子先验（与 scripts/seed_priors.py 展开逻辑一致）。"""
    out: dict[tuple[str, str], dict] = {}
    for kc in KC_POOL:
        for qt in kc.get("question_types", ["solve"]):
            out[(kc["kc_id"], qt)] = {
                "p_init": kc["bkt"]["p_init"],
                "p_transit": kc["bkt"]["p_transit"],
                "p_guess": GUESS_RATES.get(qt, kc["bkt"]["p_guess"]),
                "p_slip": kc["bkt"]["p_slip"],
            }
    return out


def replay_population(
    population: list[list[Event]],
    priors: dict[tuple[str, str], dict],
    fsrs_params: tuple | None = None,
    min_review_interval_hours: float = 20.0,
) -> list[tuple[float, int, int]]:
    """用内核 oskill.cognitive_update 按时间顺序回放，返回 (p_pred, y, attempt_idx) 列表。

    - 每次交互前用 predict_correct(state, R, difficulty) 出预测（P(L)×R 判别）。
    - min_review_interval_hours=20 与生产路径 cognitive_service 一致（集中练习去抖）。
    - state 按 (student, kc) 建，先验取首次出现的题型（与 PgStore.get_state 行为一致）。
    """
    from obase.cognitive_types import fsrs_new_card, new_state_from_prior
    from oprim.bkt import predict_correct
    from oprim.fsrs_engine import fsrs_retrievability
    from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update

    preds: list[tuple[float, int, int]] = []
    for events in population:
        states: dict[str, object] = {}
        cards: dict[str, dict] = {}
        attempts: dict[str, int] = {}
        for ev in events:
            if ev.kc_id not in states:
                prior = priors.get((ev.kc_id, ev.qtype))
                if prior is None:  # 兜底：该 KC 任意题型（同 PriorProvider 兜底 1）
                    prior = next(
                        (v for (k, _q), v in priors.items() if k == ev.kc_id),
                        {
                            "p_init": 0.2,
                            "p_transit": 0.2,
                            "p_guess": 0.15,
                            "p_slip": 0.12,
                        },
                    )
                states[ev.kc_id] = new_state_from_prior(kc_id=ev.kc_id, prior=prior)
                cards[ev.kc_id] = fsrs_new_card()
                attempts[ev.kc_id] = 0

            state, card = states[ev.kc_id], cards[ev.kc_id]
            r = fsrs_retrievability(card_dict=card, now=ev.t, parameters=fsrs_params)
            p = predict_correct(state=state, retrievability=r, difficulty=ev.difficulty)
            preds.append((float(p), int(ev.correct), attempts[ev.kc_id]))

            res = cognitive_update(
                input=CognitiveUpdateInput(
                    state=state,
                    card_dict=card,
                    is_correct=ev.correct,
                    difficulty=ev.difficulty,
                    now=ev.t,
                    min_review_interval_hours=min_review_interval_hours,
                    fsrs_parameters=fsrs_params,
                )
            )
            cards[ev.kc_id] = res.card_dict
            attempts[ev.kc_id] += 1
    return preds


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Mann-Whitney AUC（平均秩处理并列）。"""
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    n1, n0 = int(y.sum()), int((1 - y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # 并列取平均秩
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def logloss(y: np.ndarray, p: np.ndarray, eps: float = 1e-6) -> float:
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), eps, 1.0 - eps)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
