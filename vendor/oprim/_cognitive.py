"""Cognitive modeling atomic operations (BKT, FSRS)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Dict

# fsrs imported lazily inside FSRS functions (KCState/BKT don't need it)

# 单源：KCState 与初始状态工厂归 obase（杜绝 obase→oprim 反向依赖），算法仍在本模块。
from obase.cognitive_types import KCState, new_state_from_prior as bkt_new_state  # noqa: E402,F401


# ── 难度感知发射参数（BKT+IRT，Phase 0）──────────────────────────
# 在 logit 空间用题目难度 b∈[0,1] 调制 slip/guess：题越难 slip↑、guess↓。
# difficulty=None / 0.5 时完全不改变行为（逐位等价旧实现）。
_GAMMA_SLIP = 1.0
_GAMMA_GUESS = 1.0

# 红线 P(L)∈(0,0.97] 的下界：strictly >0 的最小掌握度，防退化输入压到 0/负。
_PL_FLOOR = 1e-4


def _item_adjust(
    p_guess: float, p_slip: float, difficulty: float | None
) -> tuple[float, float]:
    """据题目难度调制 (guess, slip)。difficulty=None / 0.5 → 原样返回。"""
    if difficulty is None:
        return p_guess, p_slip
    delta = difficulty - 0.5
    if delta == 0.0:  # 0.5 短路，规避 sigmoid(logit(x)) 浮点漂移
        return p_guess, p_slip
    eps = 1e-4

    def _logit(x: float) -> float:
        x = min(max(x, eps), 1.0 - eps)
        return math.log(x / (1.0 - x))

    def _sigmoid(z: float) -> float:
        return 1.0 / (1.0 + math.exp(-z))

    guess_eff = _sigmoid(_logit(p_guess) - _GAMMA_GUESS * delta)
    slip_eff = _sigmoid(_logit(p_slip) + _GAMMA_SLIP * delta)
    return guess_eff, slip_eff


def bkt_update(
    *,
    state: KCState,
    is_correct: bool,
    retrievability: float | None = None,
    days_since: float | None = None,
    difficulty: float | None = None,
) -> KCState:
    """Forgetting-aware 贝叶斯知识追踪更新（in-place + return）。
    掌握度封顶 0.97，long_term_mastery 用 EMA(α=0.4) 平滑。
    difficulty: 题目难度 b∈[0,1]（IRT）；None/0.5 不改变行为，其余在 logit
                空间调制 slip/guess。
    """
    # 0. 准备参数
    p_l = state.current()
    p_g = state.p_guess
    p_s = state.p_slip
    p_t = state.p_transit
    p_g, p_s = _item_adjust(p_g, p_s, difficulty)
    alpha = 0.4
    cap = 0.97

    # 1. Forgetting decay
    r = 1.0
    if retrievability is not None:
        r = retrievability
    elif days_since is not None:
        r = exp_forgetting(days_since=days_since)

    p_eff = p_l * r

    # 2. Bayesian update (Observation)
    if is_correct:
        p_obs = (p_eff * (1 - p_s)) / (p_eff * (1 - p_s) + (1 - p_eff) * p_g)
    else:
        p_obs = (p_eff * p_s) / (p_eff * p_s + (1 - p_eff) * (1 - p_g))

    # 3. Learning transition
    p_new = p_obs + (1 - p_obs) * p_t
    # 红线 P(L)∈(0,0.97]：上界封顶 cap，下界显式 clip 到 floor>0，
    # 防退化输入（如 r=0 / 病态先验）把掌握度压到 0 或负。
    p_new = min(max(p_new, _PL_FLOOR), cap)

    # 4. Update state (in-place)
    state.p_mastery = p_new

    if state.long_term_mastery is None:
        state.long_term_mastery = p_new
    else:
        state.long_term_mastery = alpha * p_new + (1 - alpha) * state.long_term_mastery

    state.n_attempts += 1
    # Note: last_interaction_ts update is left to the caller or handled via oskill
    return state


def bkt_error_weights(
    *, state: KCState, difficulty: float | None = None
) -> tuple[float, float]:
    """答错根因两假设的未归一化权重 (careless_weight, dontknow_weight)。

    红线公式单源（bkt_classify_error 委托本函数）：
    careless ∝ P(L) * P(S)；dontknow ∝ (1-P(L)) * (1-P(G))。
    difficulty 给定时用题目级 slip/guess（比例形式不变）。
    """
    p_l = state.current()
    p_g, p_s = _item_adjust(state.p_guess, state.p_slip, difficulty)
    return p_l * p_s, (1 - p_l) * (1 - p_g)


def bkt_classify_error(*, state: KCState, difficulty: float | None = None) -> str:
    """答错时判定根因：'careless' 或 'dontknow'。
    difficulty 给定时用题目级 slip/guess（比例形式不变）。
    """
    careless_weight, dontknow_weight = bkt_error_weights(
        state=state, difficulty=difficulty
    )
    return "careless" if careless_weight >= dontknow_weight else "dontknow"


def bkt_predict_correct(
    *,
    state: KCState,
    retrievability: float | None = None,
    difficulty: float | None = None,
) -> float:
    """预测下一次答对概率。difficulty 给定时用题目级 slip/guess。"""
    p_l = state.current()
    r = retrievability if retrievability is not None else 1.0
    p_eff = p_l * r
    p_g, p_s = _item_adjust(state.p_guess, state.p_slip, difficulty)
    return p_eff * (1 - p_s) + (1 - p_eff) * p_g


def exp_forgetting(*, days_since: float, halflife_days: float = 7.0) -> float:
    """指数遗忘近似 R = 0.5^(days/halflife)。"""
    if halflife_days <= 0:
        raise ValueError("halflife_days must be positive")
    if days_since < 0:
        raise ValueError("days_since must be non-negative")
    return 0.5 ** (days_since / halflife_days)


# bkt_new_state 已上移至 obase.cognitive_types.new_state_from_prior（顶部 import 别名为 bkt_new_state）

# FSRS Helpers (dict-based serialization)


def _card_to_dict(card) -> dict:
    return card.to_dict()


def _dict_to_card(d: dict):
    from fsrs import Card

    return Card.from_dict(d)


# FSRS 单源：实现统一在 oprim.fsrs_engine，本模块仅做"字符串 rating 接口"适配，
# 杜绝双实现漂移（D5 同源约束扩展到 FSRS）。已实证两者卡片格式/rating 决策逐位一致。


def fsrs_new_card() -> dict:
    """创建新 FSRS 记忆卡片（委托 fsrs_engine，单源）。"""
    from oprim.fsrs_engine import fsrs_new_card as _impl

    return _impl()


def fsrs_review(*, card_dict: dict, rating: str, now: datetime | None = None) -> dict:
    """对卡片做一次复习（rating 为字符串，委托 fsrs_engine）。"""
    from fsrs import Rating
    from oprim.fsrs_engine import fsrs_review as _impl

    r = {
        "Again": Rating.Again,
        "Hard": Rating.Hard,
        "Good": Rating.Good,
        "Easy": Rating.Easy,
    }.get(rating, Rating.Good)
    return _impl(card_dict=card_dict, rating=r, now=now)


def fsrs_retrievability(*, card_dict: dict, now: datetime | None = None) -> float:
    """当前可提取性 R ∈ [0,1]（委托 fsrs_engine）。"""
    from oprim.fsrs_engine import fsrs_retrievability as _impl

    return _impl(card_dict=card_dict, now=now)


def fsrs_map_rating(
    *,
    is_correct: bool,
    used_answer: bool = False,
    struggled: bool = False,
    effortless: bool = False,
) -> str:
    """表现映射为 FSRS Rating 字符串（决策委托 fsrs_engine，单源）。"""
    from oprim.fsrs_engine import fsrs_map_rating as _impl

    return _impl(
        is_correct=is_correct,
        used_answer=used_answer,
        struggled=struggled,
        effortless=effortless,
    ).name


def fsrs_due_date(*, card_dict: dict) -> str | None:
    """下次复习日期 ISO 字符串（委托 fsrs_engine）。"""
    from oprim.fsrs_engine import fsrs_due_date as _impl

    return _impl(card_dict=card_dict)
