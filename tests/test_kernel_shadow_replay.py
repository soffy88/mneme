"""The production kernel shadow adapter must remain causal and time-scoped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from services.evaluation_service import (
    ShadowReplayEvent,
    candidate_shadow_predictions,
    kernel_shadow_predictions,
)
from services.shadow_evaluation import ShadowEvaluationError

BASE = datetime(2026, 1, 1, tzinfo=UTC)
STUDENT = UUID("00000000-0000-0000-0000-000000000001")


def _event(
    day: int,
    correct: bool,
    *,
    student_id: UUID = STUDENT,
    kc: str = "kc-1",
    received_day: int | None = None,
) -> ShadowReplayEvent:
    return ShadowReplayEvent(
        event_id=uuid4(),
        student_id=student_id,
        knowledge_point=kc,
        occurred_at=BASE + timedelta(days=day),
        received_at=(
            BASE + timedelta(days=received_day)
            if received_day is not None
            else BASE + timedelta(days=day)
        ),
        is_correct=correct,
        fsrs_rating=3 if correct else 1,
        item_difficulty=None,
    )


def _replay(events: list[ShadowReplayEvent]):
    return kernel_shadow_predictions(
        events,
        model_id="kernel-v1",
        train_start=BASE,
        train_end=BASE + timedelta(days=4),
        eval_start=BASE + timedelta(days=5),
        eval_end=BASE + timedelta(days=10),
        as_of=BASE + timedelta(days=11),
    )


def test_kernel_replay_uses_train_state_and_emits_eval_only() -> None:
    train = [_event(1, True), _event(2, False)]
    gap = [_event(4, True)]
    evaluation = [_event(6, False), _event(7, True)]

    predictions = _replay(train + gap + evaluation)

    assert len(predictions) == 2
    assert [prediction.actual for prediction in predictions] == [False, True]
    assert all(
        prediction.occurred_at >= BASE + timedelta(days=5)
        for prediction in predictions
    )
    assert all(prediction.model_id == "kernel-v1" for prediction in predictions)
    assert all(prediction.event_id is not None for prediction in predictions)


def test_kernel_replay_ignores_gap_and_future_for_prior_predictions() -> None:
    train = [_event(1, True), _event(2, False)]
    evaluation = [_event(6, False), _event(7, True)]
    with_gap = _replay(train + [_event(4, True)] + evaluation)
    without_gap = _replay(train + evaluation)

    assert with_gap[0].probability == without_gap[0].probability
    assert with_gap[1].probability == without_gap[1].probability


def test_kernel_replay_keeps_students_and_kcs_isolated() -> None:
    second_student = UUID("00000000-0000-0000-0000-000000000002")
    predictions = _replay(
        [_event(1, True), _event(6, False)]
        + [
            _event(1, False, student_id=second_student),
            _event(6, True, student_id=second_student),
        ]
    )

    assert {prediction.student_id for prediction in predictions} == {
        STUDENT,
        second_student,
    }
    assert len(predictions) == 2


def test_kernel_replay_rejects_future_receipt_in_selected_window() -> None:
    with pytest.raises(ShadowEvaluationError, match="future"):
        _replay([_event(6, True, received_day=12)])


def test_kernel_replay_rejects_naive_timestamp() -> None:
    event = _event(6, True)
    event = replace(event, occurred_at=datetime(2026, 1, 7))
    with pytest.raises(ShadowEvaluationError, match="timezone-aware"):
        _replay([event])


def test_candidate_adapter_hides_current_actual_and_is_causal() -> None:
    seen_history_lengths: list[int] = []
    current_has_actual: list[bool] = []

    def predictor(history, current) -> float:
        seen_history_lengths.append(len(history))
        current_has_actual.append(hasattr(current, "actual"))
        return (
            0.5
            if not history
            else sum(item.is_correct for item in history) / len(history)
        )

    train = [_event(1, True)]
    evaluation = [_event(6, False), _event(7, True)]
    predictions = candidate_shadow_predictions(
        train + evaluation,
        model_id="candidate-v1",
        predictor=predictor,
        train_start=BASE,
        train_end=BASE + timedelta(days=4),
        eval_start=BASE + timedelta(days=5),
        eval_end=BASE + timedelta(days=10),
        as_of=BASE + timedelta(days=11),
    )

    assert len(predictions) == 2
    assert seen_history_lengths == [1, 2]
    assert current_has_actual == [False, False]
    assert predictions[0].probability == 1.0
    assert predictions[1].probability == 0.5


def test_candidate_adapter_rejects_invalid_probability_from_predictor() -> None:
    with pytest.raises(ShadowEvaluationError, match=r"\[0, 1\]"):
        candidate_shadow_predictions(
            [_event(6, True)],
            model_id="candidate-v1",
            predictor=lambda history, current: 1.1,
            train_start=BASE,
            train_end=BASE + timedelta(days=4),
            eval_start=BASE + timedelta(days=5),
            eval_end=BASE + timedelta(days=10),
            as_of=BASE + timedelta(days=11),
        )
