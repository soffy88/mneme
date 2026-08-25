"""实验 7：真实作答序列的内核 vs 序列基线影子评估（GH-3）。

本实验是 DKT/Hybrid KT challenger 接入前的最小 Evaluation OS 脚手架：

* ``kernel``：复用生产 BKT+FSRS 预测/更新路径，只在每次作答前记录预测；
* ``moving_average``：每个学生内按 KC 维护一个因果移动平均，作为透明序列基线；
* 两个模型都不训练、不写数据库、不读取未来事件。

当前 ASSISTments 预处理数据没有时间戳，因此这里和 exp5 一样将可提取性固定为
1，结果是无遗忘信号时的序列评估。将来接入带时间戳的 LearningEvent v2 时，
只需替换输入适配器，不应改变比较协议。
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence, TypeAlias

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from common import auc, logloss  # noqa: E402

SequenceEvent: TypeAlias = tuple[int, bool]
StudentSequence: TypeAlias = list[SequenceEvent]

_GENERIC_PRIOR: dict[str, float] = {
    "p_init": 0.2,
    "p_transit": 0.2,
    "p_guess": 0.15,
    "p_slip": 0.12,
}
_EPS = 1e-6
_FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Prediction:
    """一次作答前的预测及其对齐信息。"""

    skill_id: int
    attempt_idx: int
    probability: float
    actual: int


def _clamp_probability(value: float) -> float:
    return min(1.0 - _EPS, max(_EPS, float(value)))


def kernel_predictions(
    sequences: Sequence[StudentSequence],
    priors: Mapping[int, Mapping[str, float]] | None = None,
) -> list[Prediction]:
    """按生产 BKT+FSRS 路径回放，返回逐事件的作答前预测。

    ASSISTments 没有时间戳，所以使用固定时间并将 R 固定为 1；这与 exp5 的
    评估口径一致。每个学生的状态独立，避免把学生间数据泄漏到彼此序列。
    """

    from obase.cognitive_types import new_state_from_prior
    from oprim.bkt import predict_correct
    from oprim.fsrs_engine import fsrs_new_card
    from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update

    predictions: list[Prediction] = []
    for sequence in sequences:
        states: dict[int, object] = {}
        cards: dict[int, dict] = {}
        attempts: dict[int, int] = {}
        for skill_id, correct in sequence:
            if skill_id not in states:
                prior = dict((priors or {}).get(skill_id) or _GENERIC_PRIOR)
                states[skill_id] = new_state_from_prior(
                    kc_id=f"shadow-{skill_id}", prior=prior
                )
                cards[skill_id] = fsrs_new_card()
                attempts[skill_id] = 0

            state = states[skill_id]
            p = predict_correct(state=state, retrievability=1.0, difficulty=None)
            predictions.append(
                Prediction(
                    skill_id=skill_id,
                    attempt_idx=attempts[skill_id],
                    probability=_clamp_probability(float(p)),
                    actual=int(correct),
                )
            )

            # 延用 exp5 的固定时间、无去抖设置；具体 card 初始值由生产 oprim
            # 创建，避免 shadow 评估自行发明 FSRS card schema。
            res = cognitive_update(
                input=CognitiveUpdateInput(
                    state=state,
                    card_dict=cards[skill_id],
                    is_correct=bool(correct),
                    difficulty=None,
                    now=_FIXED_NOW,
                    min_review_interval_hours=0.0,
                )
            )
            cards[skill_id] = res.card_dict
            attempts[skill_id] += 1
    return predictions


def moving_average_predictions(
    sequences: Sequence[StudentSequence],
    window: int = 20,
    prior: float = 0.5,
) -> list[Prediction]:
    """每个学生内按 KC 做因果移动平均，作为透明的序列基线。

    预测发生在 append 当前结果之前；``window`` 只看该 KC 最近的历史结果，
    首次出现时使用固定 prior。该基线不使用全局统计量，故不会把不同学生的
    结果混在一起，也不需要训练阶段。
    """

    if window < 1:
        raise ValueError("window must be >= 1")
    prior = _clamp_probability(prior)
    predictions: list[Prediction] = []
    for sequence in sequences:
        history: dict[int, list[int]] = {}
        attempts: dict[int, int] = {}
        for skill_id, correct in sequence:
            values = history.setdefault(skill_id, [])
            p = prior if not values else sum(values[-window:]) / min(window, len(values))
            predictions.append(
                Prediction(
                    skill_id=skill_id,
                    attempt_idx=attempts.get(skill_id, 0),
                    probability=_clamp_probability(p),
                    actual=int(correct),
                )
            )
            values.append(int(correct))
            attempts[skill_id] = attempts.get(skill_id, 0) + 1
    return predictions


def _metric_or_none(value: float) -> float | None:
    return round(float(value), 6) if math.isfinite(float(value)) else None


def score_predictions(predictions: Sequence[Prediction]) -> dict:
    """计算 overall 与 warm-only 指标。"""

    if not predictions:
        return {
            "n": 0,
            "auc": None,
            "logloss": None,
            "base_rate": None,
            "warm_only": {"n": 0, "auc": None, "logloss": None},
        }

    p = np.asarray([item.probability for item in predictions], dtype=float)
    y = np.asarray([item.actual for item in predictions], dtype=int)
    warm = np.asarray([item.attempt_idx >= 1 for item in predictions], dtype=bool)

    def _score(mask: np.ndarray) -> tuple[float | None, float | None]:
        if not bool(mask.any()):
            return None, None
        return _metric_or_none(auc(y[mask], p[mask])), _metric_or_none(
            logloss(y[mask], p[mask])
        )

    overall_auc, overall_logloss = _score(np.ones(len(y), dtype=bool))
    warm_auc, warm_logloss = _score(warm)
    return {
        "n": int(len(y)),
        "auc": overall_auc,
        "logloss": overall_logloss,
        "base_rate": round(float(y.mean()), 6),
        "warm_only": {
            "n": int(warm.sum()),
            "auc": warm_auc,
            "logloss": warm_logloss,
        },
    }


def _delta(kernel: dict, baseline: dict) -> dict[str, float | None]:
    """返回“内核优于基线”的方向化差值。"""

    auc_delta = None
    logloss_gain = None
    if kernel["auc"] is not None and baseline["auc"] is not None:
        auc_delta = round(kernel["auc"] - baseline["auc"], 6)
    if kernel["logloss"] is not None and baseline["logloss"] is not None:
        logloss_gain = round(baseline["logloss"] - kernel["logloss"], 6)
    return {"auc_delta": auc_delta, "logloss_gain": logloss_gain}


def compare_shadow_arms(
    kernel: Sequence[Prediction], baseline: Sequence[Prediction]
) -> dict:
    """比较两条影子臂，并明确差值方向，避免把指标解释反。"""

    kernel_score = score_predictions(kernel)
    baseline_score = score_predictions(baseline)
    return {
        "kernel": kernel_score,
        "moving_average": baseline_score,
        "delta_kernel_vs_moving_average": _delta(kernel_score, baseline_score),
        "warm_only_delta": _delta(
            kernel_score["warm_only"], baseline_score["warm_only"]
        ),
    }


def load_real_sequences(
    max_students: int | None = None,
    max_len: int | None = None,
    files: tuple[str, ...] | None = None,
) -> list[StudentSequence]:
    """加载 ASSISTments 预处理序列；默认只读 test，避免把评估集混入训练语义。"""

    from exp5_external_auc import TEST_FILE, load_sequences

    return load_sequences(
        max_students=max_students,
        max_len=max_len,
        files=files or (TEST_FILE,),
    )


def run_exp7(
    max_students: int | None = None,
    max_len: int | None = None,
    window: int = 20,
) -> dict:
    """真实序列 → 两条影子臂 → AUC/log-loss 对比（纯计算）。"""

    sequences = load_real_sequences(max_students=max_students, max_len=max_len)
    kernel = kernel_predictions(sequences)
    baseline = moving_average_predictions(sequences, window=window)
    comparison = compare_shadow_arms(kernel, baseline)
    return {
        "dataset": "ASSISTments 2009-2010 skill-builder test split",
        "n_students": len(sequences),
        "n_events": len(kernel),
        "n_skills": len({skill for seq in sequences for skill, _ in seq}),
        "moving_average_window": window,
        "arms": comparison,
        "protocol": {
            "future_leakage": False,
            "writes_database": False,
            "trains_model": False,
            "timestamps_available": False,
            "retrievability": "fixed_1.0",
        },
    }


def main() -> None:
    print(json.dumps(run_exp7(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
