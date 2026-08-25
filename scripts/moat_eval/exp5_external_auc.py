"""实验 5：ASSISTments 2009-2010 真实数据外部 AUC 对标（GH-1）。

动机（outputs/GAP-REVIEW-20260817.md P0-1）：内核 AUC 此前只有合成数据验证
（exp1 ≥0.65 CI 门，目标 0.77，对标线 0.80=ASSISTments BKT 文献水平）。本实验
用公开匿名化的 ASSISTments 真实作答序列回放**与生产完全相同的算法路径**
（oskill.cognitive_update），给出外部真实数据上的判别力数字。

数据：`data/external/assist2009_updated_{train,test}.csv`（DKVMN 论文官方仓库的
ASSISTments 2009 skill-builder 预处理版，文献标准对比基准）。格式：无全局 header，
每学生 3 行：[序列长度 L, skill_id 序列, 对错序列]。公开匿名化研究数据，不入主库、
不涉未成年人 PII。

局限（诚实声明）：
- 该预处理版**无时间戳** → FSRS 遗忘维度不参与（R 恒为 1），本实验测的是
  forgetting-aware BKT 在"无遗忘信号"下的退化形态 = 纯 BKT 知识追踪。
  这恰是文献中 BKT/DKT 对比的标准口径，对标线 AUC 0.80 即此口径。
- 无题型/难度信息 → difficulty=None（不做 IRT 难度调制）。
- ASSISTments skill 无种子先验 → 用通用先验（与 common.py 兜底先验一致）。
- 序列内作答间隔未知 → min_review_interval_hours=0（不去抖）。

用法（api 容器或宿主机）：python scripts/moat_eval/exp5_external_auc.py
CI 守卫（快速档）：tests/test_external_auc.py 调 run_exp5(max_students=80, max_len=25)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

from common import auc, logloss  # noqa: E402

DATA_DIR = _REPO / "data" / "external"
TRAIN_FILE = "assist2009_updated_train.csv"
TEST_FILE = "assist2009_updated_test.csv"
FILES = (TRAIN_FILE, TEST_FILE)

# 通用先验：ASSISTments skill 无广东数学种子先验，用与 common.py replay 兜底
# 一致的通用值（p_init=0.2/p_transit=0.2/p_guess=0.15/p_slip=0.12）。
_GENERIC_PRIOR = {
    "p_init": 0.2,
    "p_transit": 0.2,
    "p_guess": 0.15,
    "p_slip": 0.12,
}


def load_sequences(
    max_students: int | None = None,
    max_len: int | None = None,
    files: tuple[str, ...] = FILES,
) -> list[list[tuple[int, bool]]]:
    """读 DKVMN 格式文件 → [(skill_id, correct), ...] per student（按文件顺序）。"""
    out: list[list[tuple[int, bool]]] = []
    for fn in files:
        path = DATA_DIR / fn
        lines = [l.strip() for l in path.open() if l.strip()]
        # DKVMN 格式：无全局 header，每学生 3 行：[长度 L, skill 序列, 对错序列]。
        i = 0
        while i + 2 < len(lines):
            try:
                L = int(lines[i])
            except ValueError:
                break
            skills = [int(x) for x in lines[i + 1].split(",") if x]
            corrects = [int(x) for x in lines[i + 2].split(",") if x]
            i += 3
            m = min(len(skills), len(corrects), L)
            if max_len is not None:
                m = min(m, max_len)
            if m < 2:
                continue
            out.append([(skills[j], bool(corrects[j])) for j in range(m)])
            if max_students is not None and len(out) >= max_students:
                return out[:max_students]
    return out


def replay_sequences(
    sequences: list[list[tuple[int, bool]]],
    priors: dict[int, dict] | None = None,
) -> list[tuple[float, int, int]]:
    """用生产算法路径回放真实作答序列，返回 (p_pred, y, attempt_idx)。

    与 exp1 的 replay_population 同构：每次交互前用 predict_correct 出预测再更新。
    无时间戳 → now 固定（R 恒 1，纯 BKT 退化）；无难度 → difficulty=None。
    priors：可选的 per-skill 先验（校准臂用）；None → 全部通用先验。
    """
    from datetime import datetime, timezone

    from obase.cognitive_types import fsrs_new_card, new_state_from_prior
    from oprim.bkt import predict_correct
    from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    preds: list[tuple[float, int, int]] = []
    for seq in sequences:
        states: dict[int, object] = {}
        cards: dict[int, dict] = {}
        attempts: dict[int, int] = {}
        for skill_id, correct in seq:
            if skill_id not in states:
                prior = (priors or {}).get(skill_id) or _GENERIC_PRIOR
                states[skill_id] = new_state_from_prior(
                    kc_id=f"assist-{skill_id}", prior=dict(prior)
                )
                cards[skill_id] = fsrs_new_card()
                attempts[skill_id] = 0
            state, card = states[skill_id], cards[skill_id]
            p = predict_correct(state=state, retrievability=1.0, difficulty=None)
            preds.append((float(p), int(correct), attempts[skill_id]))
            res = cognitive_update(
                input=CognitiveUpdateInput(
                    state=state,
                    card_dict=card,
                    is_correct=correct,
                    difficulty=None,
                    now=now,
                    min_review_interval_hours=0.0,
                )
            )
            cards[skill_id] = res.card_dict
            attempts[skill_id] += 1
    return preds


def calibrate_priors_from_train(
    train_seqs: list[list[tuple[int, bool]]]
) -> dict[int, dict]:
    """从 train 序列估计 per-skill 先验（无泄漏：只用 train，评估在 test）。

    与生产 calibration_service 同思路（数据→先验），此处用最简矩估计：
    - p_init = 该 skill 首次作答正确率（冷启动主导项）；
    - p_slip = 已连对 ≥2 次后答错的比例（高掌握却答错 → 粗心）；
    - p_guess = 首次答错者后续首次答对的比例近似（未掌握却答对）；
    - p_transit 保持通用值（短序列下矩估计噪声大，不硬拟）。
    样本不足的 skill 回退通用先验。
    """
    first: dict[int, list[bool]] = {}
    slip_num: dict[int, int] = {}
    slip_den: dict[int, int] = {}
    guess_num: dict[int, int] = {}
    guess_den: dict[int, int] = {}
    for seq in train_seqs:
        seen: dict[int, int] = {}
        run_correct: dict[int, int] = {}
        first_wrong: dict[int, bool] = {}
        for skill_id, correct in seq:
            k = seen.get(skill_id, 0)
            if k == 0:
                first.setdefault(skill_id, []).append(correct)
                first_wrong[skill_id] = not correct
            else:
                if first_wrong.get(skill_id):
                    if skill_id not in guess_num and correct:
                        guess_num[skill_id] = 1
                    if guess_num.get(skill_id, 0) == 0:
                        guess_den[skill_id] = guess_den.get(skill_id, 0) + 1
                if run_correct.get(skill_id, 0) >= 2:
                    slip_den[skill_id] = slip_den.get(skill_id, 0) + 1
                    if not correct:
                        slip_num[skill_id] = slip_num.get(skill_id, 0) + 1
            run_correct[skill_id] = (run_correct.get(skill_id, 0) + 1) if correct else 0
            seen[skill_id] = k + 1

    out: dict[int, dict] = {}
    for skill_id, fs in first.items():
        if len(fs) < 10:
            continue
        prior = dict(_GENERIC_PRIOR)
        prior["p_init"] = min(max(sum(fs) / len(fs), 0.01), 0.97)
        if slip_den.get(skill_id, 0) >= 10:
            prior["p_slip"] = min(
                max(slip_num[skill_id] / slip_den[skill_id], 0.02), 0.35
            )
        if guess_den.get(skill_id, 0) >= 10:
            prior["p_guess"] = min(
                max(guess_num.get(skill_id, 0) / guess_den[skill_id], 0.02), 0.45
            )
        out[skill_id] = prior
    return out


def run_exp5(
    max_students: int | None = None, max_len: int | None = None
) -> dict:
    """加载真实序列→内核回放→指标。max_students/max_len 供快速档（CI 守卫）。

    两个臂（无泄漏）：
    - generic：全部通用先验，train+test 合并回放（冷启动基线）；
    - calibrated：train 拟合 per-skill 先验 → 仅 test 回放（数据飞轮增益）。
    """
    sequences = load_sequences(max_students=max_students, max_len=max_len)
    preds = replay_sequences(sequences)
    p = np.array([x[0] for x in preds])
    y = np.array([x[1] for x in preds])
    attempt = np.array([x[2] for x in preds])
    warm = attempt >= 1
    n_skills = len({s for seq in sequences for s, _ in seq})

    # 校准臂：train 拟合 → test 评估（快速档下样本不足则跳过）
    calib: dict | None = None
    if max_students is None or max_students >= 200:
        train_seqs = load_sequences(files=(TRAIN_FILE,))
        test_seqs = load_sequences(files=(TEST_FILE,))
        priors = calibrate_priors_from_train(train_seqs)
        if priors:
            tp = replay_sequences(test_seqs, priors=priors)
            tp_arr = np.array([x[0] for x in tp])
            ty_arr = np.array([x[1] for x in tp])
            ta = np.array([x[2] for x in tp])
            tw = ta >= 1
            calib = {
                "n_calibrated_skills": len(priors),
                "n_test_students": len(test_seqs),
                "n_test_events": int(len(tp_arr)),
                "overall": {
                    "auc": round(auc(ty_arr, tp_arr), 3),
                    "logloss": round(logloss(ty_arr, tp_arr), 3),
                },
                "warm_only": {
                    "n": int(tw.sum()),
                    "auc": round(auc(ty_arr[tw], tp_arr[tw]), 3),
                    "logloss": round(logloss(ty_arr[tw], tp_arr[tw]), 3),
                },
                "target_077": bool(auc(ty_arr, tp_arr) >= 0.77),
                "benchmark_080": bool(auc(ty_arr, tp_arr) >= 0.80),
            }

    return {
        "dataset": "ASSISTments 2009-2010 skill-builder (DKVMN preprocessed)",
        "n_students": len(sequences),
        "n_events": int(len(p)),
        "n_skills": n_skills,
        "avg_events_per_student": round(len(p) / max(1, len(sequences)), 1),
        "generic_priors": {
            "overall": {"auc": round(auc(y, p), 3), "logloss": round(logloss(y, p), 3)},
            "warm_only": {
                "n": int(warm.sum()),
                "auc": round(auc(y[warm], p[warm]), 3),
                "logloss": round(logloss(y[warm], p[warm]), 3),
            },
            "base_rate_correct": round(float(y.mean()), 3),
            "target_077": bool(auc(y, p) >= 0.77),
            "benchmark_080": bool(auc(y, p) >= 0.80),
        },
        "calibrated_priors_train_to_test": calib,
    }


def main() -> None:
    result = run_exp5()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
