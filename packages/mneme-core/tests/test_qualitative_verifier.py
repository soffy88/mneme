"""Tests for qualitative_verifier — SPEC §3 / §10 (oskill, ≥8 scenarios).

All tests inject a scripted fake LLMCaller (fixed messages → fixed JSON), so the
element is exercised end-to-end with zero provider dependency.
"""

import json

import pytest

from mneme_core.oprim.models import KpView, Rubric, RubricDimension
from mneme_core.oskill.qualitative_verifier import qualitative_verifier

EXPL = "a function maps each x to exactly one y with a domain and a range"
KP = KpView(kc_id="k", name="Function", gate_type="qualitative")
RUBRIC = Rubric(
    kc_id="k",
    dimensions=(
        RubricDimension(name="d1", criterion="c1", weight=0.5),
        RubricDimension(name="d2", criterion="c2", weight=0.5),
    ),
)


def _caller(payload):
    """Fake LLMCaller: dict→json, str→raw (for malformed-output test)."""

    def call(*, messages):
        assert isinstance(messages, list) and messages  # element built a prompt
        return (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )

    return call


def _span(quote):
    i = EXPL.index(quote)
    return {"start": i, "end": i + len(quote), "quote": quote}


def test_all_dimensions_pass():
    llm = _caller(
        {
            "dimensions": [
                {"name": "d1", "passed": True, "spans": [_span("function")]},
                {"name": "d2", "passed": True, "spans": [_span("domain")]},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    assert v.passed is True
    assert v.score == pytest.approx(1.0)
    assert len(v.evidence_spans) == 2


def test_single_dimension_fail_fails_overall():
    llm = _caller(
        {
            "dimensions": [
                {"name": "d1", "passed": True, "spans": [_span("function")]},
                {"name": "d2", "passed": False, "spans": []},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    assert v.passed is False
    assert v.score == pytest.approx(0.5)  # only d1's weight counted


def test_span_out_of_range_rejected():
    llm = _caller(
        {
            "dimensions": [
                {
                    "name": "d1",
                    "passed": True,
                    "spans": [{"start": 1000, "end": 1005, "quote": "xxxxx"}],
                },
                {"name": "d2", "passed": True, "spans": [_span("domain")]},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    d1 = next(d for d in v.dimensions if d.name == "d1")
    assert d1.passed is False  # out-of-range span → not anchored
    assert v.passed is False


def test_hallucinated_quote_rejected():
    """start/end in range but quote != explanation[start:end] → hallucination guard."""
    i = EXPL.index("function")
    llm = _caller(
        {
            "dimensions": [
                {
                    "name": "d1",
                    "passed": True,
                    "spans": [
                        {"start": i, "end": i + len("function"), "quote": "WRONG"}
                    ],
                },
                {"name": "d2", "passed": True, "spans": [_span("domain")]},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    d1 = next(d for d in v.dimensions if d.name == "d1")
    assert d1.passed is False
    assert "幻觉" in d1.reason or "回验" in d1.reason
    assert v.passed is False


def test_passed_but_no_span_rejected():
    """LLM claims passed with zero spans → cannot anchor → dimension fails."""
    llm = _caller(
        {
            "dimensions": [
                {"name": "d1", "passed": True, "spans": []},
                {"name": "d2", "passed": True, "spans": [_span("domain")]},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    assert next(d for d in v.dimensions if d.name == "d1").passed is False
    assert v.passed is False


def test_rubric_weights_not_one_raises():
    bad = Rubric(
        kc_id="k",
        dimensions=(
            RubricDimension(name="d1", criterion="c1", weight=0.5),
            RubricDimension(name="d2", criterion="c2", weight=0.3),
        ),
    )
    with pytest.raises(ValueError):
        qualitative_verifier(EXPL, rubric=bad, kp=KP, llm=_caller({"dimensions": []}))


def test_empty_explanation_cannot_anchor():
    llm = _caller(
        {
            "dimensions": [
                {
                    "name": "d1",
                    "passed": True,
                    "spans": [{"start": 0, "end": 3, "quote": "abc"}],
                },
                {
                    "name": "d2",
                    "passed": True,
                    "spans": [{"start": 0, "end": 1, "quote": "z"}],
                },
            ]
        }
    )
    v = qualitative_verifier("", rubric=RUBRIC, kp=KP, llm=llm)
    assert v.passed is False
    assert v.evidence_spans == ()


def test_malformed_llm_output_tolerated():
    """Non-JSON output must not crash; degrades to no dimension anchored."""
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=_caller("not json {{["))
    assert v.passed is False
    assert all(d.passed is False for d in v.dimensions)


def test_multi_span_single_dimension():
    llm = _caller(
        {
            "dimensions": [
                {
                    "name": "d1",
                    "passed": True,
                    "spans": [_span("function"), _span("range")],
                },
                {"name": "d2", "passed": True, "spans": [_span("domain")]},
            ]
        }
    )
    v = qualitative_verifier(EXPL, rubric=RUBRIC, kp=KP, llm=llm)
    assert v.passed is True
    d1 = next(d for d in v.dimensions if d.name == "d1")
    assert len(d1.spans) == 2
    assert len(v.evidence_spans) == 3  # 2 + 1
