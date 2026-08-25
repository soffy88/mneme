"""Blueprint P5 Evaluation OS: explicit no-AI and time-split contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from event_schema import legacy_interaction_to_event
from services.evaluation_os import (
    EvaluationObservation,
    delayed_gain_metric,
    evaluation_report,
    no_ai_transfer_metric,
    time_split_counts,
)


BASE = datetime(2026, 8, 1, tzinfo=UTC)


def _row(
    sid: UUID,
    at: datetime,
    correct: bool,
    source: str = "review",
    **kwargs,
) -> EvaluationObservation:
    return EvaluationObservation(
        student_id=sid,
        occurred_at=at,
        is_correct=correct,
        source=source,
        **kwargs,
    )


def test_no_ai_transfer_requires_explicit_independent_and_ai_flags():
    sid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    rows = [
        _row(
            sid,
            BASE,
            True,
            "transfer_probe",
            independent_mode=True,
            ai_assisted=False,
        ),
        # A legacy/ambiguous row remains in the ordinary transfer metric only.
        _row(sid, BASE + timedelta(days=1), False, "transfer_probe"),
    ]

    result = no_ai_transfer_metric(rows)
    report = evaluation_report(rows, now=BASE + timedelta(days=40))

    assert result["value"] == 1.0
    assert result["n"] == 1
    assert report["no_ai_transfer"]["n"] == 1
    assert report["guardrails"]["no_ai_requires_explicit_flags"] is True


def test_delayed_gain_is_paired_by_student_and_missing_pairs_are_null():
    sid_a = uuid4()
    sid_b = uuid4()
    rows = [
        _row(sid_a, BASE, False, evaluation_phase="baseline"),
        _row(sid_a, BASE + timedelta(days=7), True, evaluation_phase="delayed"),
        _row(sid_b, BASE, True, evaluation_phase="baseline"),
    ]

    result = delayed_gain_metric(rows)

    assert result["value"] == 1.0
    assert result["paired_n"] == 1
    assert result["positive_gain_rate"] == 1.0


def test_time_split_excludes_future_receipts_and_rejects_overlap():
    sid = uuid4()
    rows = [
        _row(sid, BASE, True),
        _row(sid, BASE + timedelta(days=10), True),
        _row(
            sid,
            BASE + timedelta(days=11),
            True,
            received_at=BASE + timedelta(days=30),
        ),
    ]
    result = time_split_counts(
        rows,
        train_end=BASE + timedelta(days=5),
        eval_start=BASE + timedelta(days=7),
        eval_end=BASE + timedelta(days=14),
        as_of=BASE + timedelta(days=20),
    )

    assert result["train_n"] == 1
    assert result["evaluation_n"] == 1
    assert result["future_excluded_n"] == 1
    assert result["overlap"] is False
    with pytest.raises(ValueError):
        time_split_counts(
            rows,
            train_end=BASE + timedelta(days=8),
            eval_start=BASE + timedelta(days=7),
            eval_end=BASE + timedelta(days=14),
        )


def test_legacy_adapter_preserves_evaluation_signals_in_v2_intervention():
    event = legacy_interaction_to_event(
        SimpleNamespace(
            id=uuid4(),
            student_id=uuid4(),
            knowledge_point="ku-1",
            question_id=None,
            occurred_at=BASE,
            source="transfer_probe",
            is_correct=True,
            tutor_mode="independent_transfer",
            ai_assisted=False,
            independent_mode=True,
            evaluation_phase="delayed",
        )
    )

    assert event.intervention == {
        "tutor_mode": "independent_transfer",
        "ai_assisted": False,
        "independent_mode": True,
        "evaluation_phase": "delayed",
    }
