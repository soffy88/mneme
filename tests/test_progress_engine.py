"""ProgressEngine unit tests: coverage/progress percentage math.

Pure-logic tests for the projection dataclasses (DB-backed rebuild logic
is exercised in the P8 real-user-flow E2E).
"""

from __future__ import annotations

from services.progress_engine import BookProgress, ExamCoverage


# ---------- ExamCoverage ----------

def test_exam_coverage_touched_pct():
    c = ExamCoverage(scope="ZHONGKAO", total=1840, touched=1032, mastered=814)
    assert c.touched_pct == 56.1
    assert c.mastered_pct == 44.2


def test_exam_coverage_zero_total():
    c = ExamCoverage(scope="GAOKAO", total=0, touched=0, mastered=0)
    assert c.touched_pct == 0.0
    assert c.mastered_pct == 0.0


def test_exam_coverage_mastered_never_exceeds_touched():
    c = ExamCoverage(scope="ZHONGKAO", total=100, touched=30, mastered=25)
    assert c.mastered <= c.touched


# ---------- BookProgress ----------

def test_book_progress_lesson_pct():
    b = BookProgress(book_id="b1", completed_lessons=62, total_lessons=100, vocab_mastered=48, vocab_total=100)
    assert b.lesson_pct == 62.0
    assert b.vocab_pct == 48.0


def test_book_progress_zero_total():
    b = BookProgress(book_id="b1", completed_lessons=0, total_lessons=0, vocab_mastered=0, vocab_total=0)
    assert b.lesson_pct == 0.0
    assert b.vocab_pct == 0.0


def test_book_progress_lesson_and_vocab_separate():
    """Lesson completion and vocab mastery are distinct (SPEC §39)."""
    b = BookProgress(book_id="b1", completed_lessons=80, total_lessons=100, vocab_mastered=30, vocab_total=100)
    assert b.lesson_pct == 80.0
    assert b.vocab_pct == 30.0
    assert b.lesson_pct != b.vocab_pct
