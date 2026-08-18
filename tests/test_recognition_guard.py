"""exp6 recognition 维度独立验证守卫（GH-2，M-G §4.5）。

动机（outputs/GAP-REVIEW-20260817.md P3-3）：moat_eval exp1-5 从未测过识别
维度。本守卫在显式双维度真值世界上回放生产算法路径，断言三件事不回退：

1. 判别增益：迁移测试上 P(mixed)=pr·P(mastery)+(1-pr)·guess 的 AUC 高于
   仅 mastery 预测（识别维度必须提供 mastery 之外的信息）。
2. 惰性知识捕获：专项型群体终态 p_recognition 低于交错型，且迁移测试错误率更高。
3. 校准增益：带识别的预测 logloss 低于仅 mastery（方向与幅度一致）。

- 纯计算不碰任何数据库（numpy 真值世界 + oskill.cognitive_update 回放）。
- 快速档（n_students=60）默认跑；MOAT=1 跑全量档（n_students=150）：
    MOAT=1 python -m pytest tests/test_recognition_guard.py -q --no-cov
- 门槛依据（2026-08-18 首跑，7 seeds × 150 生）：
    recognition_gain_auc ∈ [0.012, 0.063]，logloss 降幅 ≥ 0.10，
    终态 p_recognition 交错型 > 专项型、迁移错误率 专项型 > 交错型 全部成立。
  快速档样本小，故只守方向性断言（gain>0、inert 捕获、logloss 改善），
  不设绝对 AUC 门——真值世界与内核刻意不同源，绝对值随世界参数漂移。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.moat

_MOAT_FULL = os.environ.get("MOAT") == "1"

FAST_N_STUDENTS = 60
FULL_N_STUDENTS = 150


def _run_exp6(n_students: int) -> dict:
    moat_dir = str(Path(__file__).resolve().parents[1] / "scripts" / "moat_eval")
    if moat_dir not in sys.path:
        sys.path.insert(0, moat_dir)
    from exp6_recognition import run_exp6

    return run_exp6(n_students=n_students)


@pytest.fixture(scope="module")
def result() -> dict:
    n = FULL_N_STUDENTS if _MOAT_FULL else FAST_N_STUDENTS
    return _run_exp6(n)


def test_recognition_gain_auc_positive(result: dict) -> None:
    """判别增益：带识别的混合情境预测 AUC 必须高于仅 mastery（维度有信息量）。"""
    assert result["n_mixed_events"] > 200, "迁移测试事件量异常，规模参数可能被改动"
    assert result["gain_positive"], (
        f"recognition_gain_auc={result['recognition_gain_auc']} ≤ 0——"
        "识别维度未提供 mastery 之外的判别信息，检查 p_recognition 更新路径"
    )


def test_inert_knowledge_captured(result: dict) -> None:
    """惰性知识：交错型终态 p_recognition 高于专项型（内核区分了两类群体）。"""
    assert result["inert_knowledge_captured"], (
        f"终态 p_recognition 专项型={result['final_recog_focused_mean']} ≥ "
        f"交错型={result['final_recog_interleaved_mean']}——"
        "内核未捕获惰性知识，检查 is_interleaved 分支"
    )


def test_focused_group_higher_mixed_error(result: dict) -> None:
    """惰性知识真值侧：专项型群体迁移测试错误率高于交错型。"""
    assert (
        result["mixed_error_rate_focused"] > result["mixed_error_rate_interleaved"]
    ), (
        f"迁移测试错误率 专项型={result['mixed_error_rate_focused']} ≤ "
        f"交错型={result['mixed_error_rate_interleaved']}——真值世界对照组失效"
    )


def test_recognition_improves_logloss(result: dict) -> None:
    """校准增益：带识别预测的 logloss 必须低于仅 mastery（不只是排序）。"""
    assert result["logloss_with_recognition"] < result["logloss_mastery_only"], (
        f"logloss 带识别={result['logloss_with_recognition']} ≥ "
        f"仅 mastery={result['logloss_mastery_only']}——识别维度损害校准"
    )
