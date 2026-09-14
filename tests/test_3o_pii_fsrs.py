"""Adversarial guards for the canonical omodul audit boundary."""

from datetime import datetime, timezone

import pytest

from omodul._base import Trail
from omodul._fingerprint import _hash_input_data
from omodul.echo_loop_session import SpacedReviewConfig, SpacedReviewInput, spaced_review_schedule
from services.anon import anon_ref


def test_identity_is_not_hashed_into_omodul_input_fingerprint() -> None:
    public = _hash_input_data({"subject_ref": "ref-a", "answer": "ok"}, strategy="dict")
    with_identity = _hash_input_data(
        {"subject_ref": "ref-a", "student_id": "raw-student-id", "answer": "ok"},
        strategy="dict",
    )
    assert with_identity == public


def test_identity_is_removed_from_decision_trail() -> None:
    trail = Trail()
    trail.record(event="probe", student_id="raw-student-id", subject_ref="ref-a")
    assert "student_id" not in trail.steps[0]
    assert trail.steps[0]["subject_ref"] == "ref-a"


def test_anon_ref_is_stable_distinct_and_non_revealing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEME_ANON_SALT", "deployment-project-test-salt")
    first = anon_ref("student-a")
    assert first == anon_ref("student-a")
    assert first != anon_ref("student-b")
    assert "student-a" not in first


@pytest.mark.asyncio
async def test_fixed_interval_is_recommendation_only(tmp_path) -> None:
    result = await spaced_review_schedule(
        SpacedReviewConfig(),
        SpacedReviewInput(
            subject_ref="ref-a",
            material_id="material-a",
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        tmp_path,
    )
    assert result["recommendation_only"] is True
    assert result["next_review_at"] is None
