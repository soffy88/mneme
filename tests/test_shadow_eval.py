"""GH-3：序列影子评估的因果性与指标契约。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

MOAT_DIR = str(Path(__file__).resolve().parents[1] / "scripts" / "moat_eval")
if MOAT_DIR not in sys.path:
    sys.path.insert(0, MOAT_DIR)

from exp7_shadow_eval import (  # noqa: E402
    compare_shadow_arms,
    kernel_predictions,
    moving_average_predictions,
    score_predictions,
)


def test_moving_average_is_causal_and_per_student_per_skill() -> None:
    sequences = [[(1, True), (1, False), (2, False), (1, True)]]
    predictions = moving_average_predictions(sequences, window=2, prior=0.5)

    assert [p.attempt_idx for p in predictions] == [0, 1, 0, 2]
    assert [p.probability for p in predictions] == pytest.approx(
        [0.5, 0.999999, 0.5, 0.5], abs=1e-9
    )

    with_future = moving_average_predictions(
        [[(1, True), (1, False), (1, False)]], window=2
    )
    without_future = moving_average_predictions([[(1, True), (1, False)]], window=2)
    assert [p.probability for p in with_future[:2]] == [
        p.probability for p in without_future
    ]


def test_score_predictions_reports_overall_and_warm_only() -> None:
    predictions = moving_average_predictions(
        [[(1, True), (1, True), (1, False)], [(2, False), (2, True)]],
        window=2,
    )

    result = score_predictions(predictions)

    assert result["n"] == 5
    assert result["warm_only"]["n"] == 3
    assert result["auc"] is not None
    assert result["logloss"] is not None


def test_kernel_replay_emits_causal_predictions() -> None:
    predictions = kernel_predictions([[(7, True), (7, False), (8, True)]])

    assert len(predictions) == 3
    assert [p.skill_id for p in predictions] == [7, 7, 8]
    assert [p.attempt_idx for p in predictions] == [0, 1, 0]
    assert all(0.0 < p.probability < 1.0 for p in predictions)


def test_compare_shadow_arms_keeps_delta_direction_explicit() -> None:
    kernel = moving_average_predictions([[(1, True), (1, True)]])
    baseline = moving_average_predictions([[(1, False), (1, False)]])

    result = compare_shadow_arms(kernel, baseline)

    assert set(result) == {
        "kernel",
        "moving_average",
        "delta_kernel_vs_moving_average",
        "warm_only_delta",
    }
    assert "auc_delta" in result["delta_kernel_vs_moving_average"]
    assert "logloss_gain" in result["delta_kernel_vs_moving_average"]


def test_moving_average_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="window"):
        moving_average_predictions([[(1, True)]], window=0)
