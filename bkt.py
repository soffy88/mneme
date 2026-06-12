"""
BKT 知识追踪引擎（forgetting-aware）
====================================
对每个知识点(KC)维护掌握概率 P(L)，每次答题事件后做贝叶斯更新。

相比 v1.2 的 `0.7旧+0.3新` 拍脑袋公式，BKT 的优势：
1. 有概率意义，可解释
2. slip/guess 参数天然支持「粗心 vs 不会」的客观判定
3. 可用 AUC 验证预测准确度

forgetting-aware：在贝叶斯更新前，用一个遗忘因子 R 衰减先验掌握度，
使「掌握度」会随时间流逝而下降，而非「学会就永远是高值」。
R 由 FSRS 的可提取性提供（见 cognitive_state.py 的协同）；
本模块也内置一个独立的指数遗忘近似，便于单独测试。
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import math


@dataclass
class KCState:
    """单个学生在单个知识点上的认知状态。"""
    kc_id: str
    p_init: float = 0.20
    p_transit: float = 0.20
    p_guess: float = 0.15
    p_slip: float = 0.12
    p_mastery: Optional[float] = None        # 当前掌握概率 P(L)，None=用先验
    long_term_mastery: Optional[float] = None  # 去遗忘的长期掌握度（展示用）
    last_interaction_ts: Optional[float] = None  # 上次接触的 unix 时间戳
    n_attempts: int = 0

    def current(self) -> float:
        return self.p_mastery if self.p_mastery is not None else self.p_init


# 边界保护，避免 0/1 导致数值僵死
_EPS = 1e-4
def _clip(x, lo=_EPS, hi=1 - _EPS):
    return max(lo, min(hi, x))

# 掌握度上限：现实中没有"100%掌握"，封顶避免过度自信，
# 也给 forgetting-aware 衰减留出空间。
_MASTERY_CAP = 0.97


def exp_forgetting(days_since: float, halflife_days: float = 7.0) -> float:
    """独立的指数遗忘近似：R = 0.5 ** (days/halflife)。
    仅在没有 FSRS 的 R 输入时使用（便于单元测试 BKT 本身）。"""
    if days_since <= 0:
        return 1.0
    return 0.5 ** (days_since / halflife_days)


def bkt_update(state: KCState, is_correct: bool,
               retrievability: Optional[float] = None,
               days_since: Optional[float] = None) -> KCState:
    """对一次答题事件做 forgetting-aware BKT 更新。

    retrievability: FSRS 提供的可提取性 R (0~1)。若为 None，则用 days_since
                    走内置指数遗忘；若两者都 None，视为无遗忘 (R=1)。
    """
    P_L = state.current()
    P_G, P_S, P_T = state.p_guess, state.p_slip, state.p_transit

    # 1) forgetting-aware：衰减先验掌握度
    if retrievability is not None:
        R = _clip(retrievability, 0.0, 1.0)
    elif days_since is not None:
        R = exp_forgetting(days_since)
    else:
        R = 1.0
    P_L_eff = _clip(P_L * R)

    # 2) 贝叶斯观测更新
    if is_correct:
        num = P_L_eff * (1 - P_S)
        den = P_L_eff * (1 - P_S) + (1 - P_L_eff) * P_G
    else:
        num = P_L_eff * P_S
        den = P_L_eff * P_S + (1 - P_L_eff) * (1 - P_G)
    P_L_obs = _clip(num / den) if den > 0 else P_L_eff

    # 3) 应用学习（这次练习本身的提升）
    P_L_new = _clip(P_L_obs + (1 - P_L_obs) * P_T, hi=_MASTERY_CAP)

    # 更新状态
    state.p_mastery = P_L_new
    # 长期掌握度：用 EMA 平滑，剔除短期遗忘波动（展示成长曲线用）
    base = P_L_new if state.long_term_mastery is None else state.long_term_mastery
    state.long_term_mastery = _clip(0.6 * base + 0.4 * P_L_new) \
        if state.long_term_mastery is not None else P_L_new
    state.n_attempts += 1
    return state


def classify_error(state: KCState) -> str:
    """答错时区分『粗心』vs『不会』。
    依据：粗心权重 ∝ P(L)·P(S)；不会权重 ∝ (1-P(L))·(1-P(G))。
    """
    P_L = state.current()
    careless = P_L * state.p_slip
    dontknow = (1 - P_L) * (1 - state.p_guess)
    return "careless" if careless > dontknow else "dontknow"


def predict_correct(state: KCState, retrievability: Optional[float] = None) -> float:
    """预测学生下一题答对的概率（用于 AUC 评估）。
    P(correct) = P(L_eff)·(1-slip) + (1-P(L_eff))·guess
    """
    R = 1.0 if retrievability is None else _clip(retrievability, 0.0, 1.0)
    P_L_eff = _clip(state.current() * R)
    return P_L_eff * (1 - state.p_slip) + (1 - P_L_eff) * state.p_guess


def new_state_from_prior(kc_id: str, prior: dict) -> KCState:
    return KCState(
        kc_id=kc_id,
        p_init=prior["p_init"], p_transit=prior["p_transit"],
        p_guess=prior["p_guess"], p_slip=prior["p_slip"],
    )
