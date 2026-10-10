"""LearningEngine unit tests: scoring, FSRS rating policy, task selection.

Pure-logic tests (no DB) for services/learning_scoring.py and the
task-selection / classification logic of services/learning_engine.py.
"""

from __future__ import annotations



from services.learning_engine import LearningEngine, TaskType, _kp
from services.learning_scoring import (
    FSRSRating,
    Score,
    derive_fsrs_rating,
    score_cloze,
    score_en_to_zh,
    score_listening,
    score_spelling,
    score_zh_to_en,
)


# ---------- EN_TO_ZH ----------

def test_en_to_zh_exact():
    assert score_en_to_zh("机场", "机场").score == Score.CORRECT


def test_en_to_zh_alias():
    assert score_en_to_zh("机场", "航空港", aliases=["航空港"]).score == Score.CORRECT


def test_en_to_zh_synonym_partial():
    r = score_en_to_zh("飞机场", "机场")
    assert r.score == Score.PARTIAL


def test_en_to_zh_incorrect():
    assert score_en_to_zh("机场", "火车站").score == Score.INCORRECT


# ---------- ZH_TO_EN ----------

def test_zh_to_en_exact():
    assert score_zh_to_en("airport", "airport").score == Score.CORRECT


def test_zh_to_en_case_insensitive():
    assert score_zh_to_en("airport", "Airport").score == Score.CORRECT


def test_zh_to_en_whitespace():
    assert score_zh_to_en("airport", "  airport  ").score == Score.CORRECT


def test_zh_to_en_incorrect():
    assert score_zh_to_en("airport", "airprot").score == Score.INCORRECT


# ---------- SPELLING ----------

def test_spelling_exact():
    assert score_spelling("airport", "airport").score == Score.CORRECT


def test_spelling_case():
    assert score_spelling("airport", "Airport").score == Score.CORRECT


def test_spelling_one_edit_partial():
    r = score_spelling("airport", "airpot")
    assert r.score == Score.PARTIAL
    assert "edit_distance=1" in r.detail


def test_spelling_far_incorrect():
    assert score_spelling("airport", "xyz").score == Score.INCORRECT


# ---------- CLOZE ----------

def test_cloze_correct():
    assert score_cloze("airport", "airport", "I went to the airport.").score == Score.CORRECT


def test_cloze_incorrect():
    assert score_cloze("airport", "xyz", "I went to the airport.").score == Score.INCORRECT


# ---------- LISTENING ----------

def test_listening_correct():
    assert score_listening("airport", "airport").score == Score.CORRECT


# ---------- FSRS rating policy ----------

def test_rating_incorrect_is_again():
    assert derive_fsrs_rating(Score.INCORRECT) == FSRSRating.AGAIN


def test_rating_skipped_is_again():
    assert derive_fsrs_rating(Score.SKIPPED) == FSRSRating.AGAIN


def test_rating_partial_is_hard():
    assert derive_fsrs_rating(Score.PARTIAL) == FSRSRating.HARD


def test_rating_hint_is_hard():
    assert derive_fsrs_rating(Score.CORRECT, used_hint=True) == FSRSRating.HARD


def test_rating_correct_normal_is_good():
    assert derive_fsrs_rating(Score.CORRECT, latency_ms=5000) == FSRSRating.GOOD


def test_rating_correct_fast_is_easy():
    assert derive_fsrs_rating(Score.CORRECT, latency_ms=1000) == FSRSRating.EASY


# ---------- task selection ----------

def _engine() -> LearningEngine:
    # Task selection is pure logic; db is not exercised here.
    return LearningEngine(db=None)  # type: ignore[arg-type]


def test_task_new_is_en_to_zh():
    assert _engine().select_task("NEW") == TaskType.EN_TO_ZH


def test_task_learning_is_zh_to_en():
    assert _engine().select_task("LEARNING") == TaskType.ZH_TO_EN


def test_task_learning_failed_is_cloze():
    assert _engine().select_task("LEARNING", failed_before=True) == TaskType.CONTEXT_CLOZE


def test_task_review_is_cloze():
    assert _engine().select_task("REVIEW") == TaskType.CONTEXT_CLOZE


def test_task_mastered_is_listening():
    assert _engine().select_task("MASTERED") == TaskType.LISTENING_RECOGNITION


# ---------- vocab kp key ----------

def test_vocab_kp_key():
    assert _kp("abc") == "vocab-abc"
