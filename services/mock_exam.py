"""Mock exam packaging (Parroto method, clean rewrite).

A mock exam is only packaging over the existing wrong-question pool:
sections reference WrongQuestion ids, assembly exposes question texts
only (never answers), and scoring reuses the deterministic graders.
Submitting writes exactly one append-only attempt row; it never writes
BKT/FSRS. Late submissions still score, flagged late.
"""

from __future__ import annotations

from typing import Any, Mapping

MAX_SECTIONS = 6
MAX_QUESTIONS = 50
MIN_SECTION_SECONDS = 30
MAX_SECTION_SECONDS = 3600
MIN_TOTAL_SECONDS = 60
MAX_TOTAL_SECONDS = 10800


class MockExamIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def _is_bilingual(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("zh"), str)
        and value["zh"].strip() != ""
        and isinstance(value.get("en"), str)
        and value["en"].strip() != ""
    )


def verify_mock_exam_spec(
    spec: Mapping[str, Any], existing_ids: set[str]
) -> tuple[dict[str, bool], list[MockExamIssue]]:
    """Six gates. Existence is checked against caller-supplied ids."""
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 7)}
    issues: list[MockExamIssue] = []

    def fail(gate: str, issue: MockExamIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        return gates, [MockExamIssue("", "not_an_object", "spec must be an object")]
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id or len(spec_id) > 100:
        fail("g1", MockExamIssue("id", "bad_id", "id must be a non-empty string of at most 100 chars"))
    if not _is_bilingual(spec.get("title")):
        fail("g2", MockExamIssue("title", "bad_title", "title must carry non-empty zh and en"))
    if not isinstance(spec.get("subject"), str) or not spec.get("subject"):
        fail("g2", MockExamIssue("subject", "bad_subject", "subject must be a non-empty string"))
    level = spec.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
        fail("g2", MockExamIssue("level", "bad_level", "level must be an integer from 1 to 5"))
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        fail("g3", MockExamIssue("sections", "missing_sections", "sections must be a non-empty list"))
        sections = []
    if len(sections) > MAX_SECTIONS:
        fail("g3", MockExamIssue("sections", "too_many_sections", "too many sections"))
    seen: set[str] = set()
    section_seconds = 0
    for pos, section in enumerate(sections):
        field = f"sections[{pos}]"
        if not isinstance(section, dict):
            fail("g3", MockExamIssue(field, "not_an_object", "section must be an object"))
            continue
        if not _is_bilingual(section.get("name")):
            fail("g3", MockExamIssue(f"{field}.name", "bad_name", "section name must carry non-empty zh and en"))
        seconds = section.get("seconds")
        if (
            not isinstance(seconds, int)
            or isinstance(seconds, bool)
            or not MIN_SECTION_SECONDS <= seconds <= MAX_SECTION_SECONDS
        ):
            fail("g3", MockExamIssue(f"{field}.seconds", "bad_seconds", "section seconds out of range"))
        else:
            section_seconds += seconds
        qids = section.get("question_ids")
        if not isinstance(qids, list) or not qids:
            fail("g4", MockExamIssue(f"{field}.question_ids", "missing_questions", "section must list at least one question"))
            continue
        for qid in qids:
            if not isinstance(qid, str) or not qid:
                fail("g4", MockExamIssue(f"{field}.question_ids", "bad_question_id", "question ids must be non-empty strings"))
            elif qid in seen:
                fail("g4", MockExamIssue(f"{field}.question_ids", "duplicate_question", "question ids must not repeat across sections"))
            elif qid not in existing_ids:
                fail("g4", MockExamIssue(f"{field}.question_ids", "question_not_found", "question id does not exist"))
            seen.add(qid)
    if len(seen) > MAX_QUESTIONS:
        fail("g4", MockExamIssue("sections", "too_many_questions", "too many questions"))
    total = spec.get("total_seconds")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or not MIN_TOTAL_SECONDS <= total <= MAX_TOTAL_SECONDS
    ):
        fail("g5", MockExamIssue("total_seconds", "bad_total_seconds", "total_seconds out of range"))
    elif sections and total != section_seconds:
        fail("g5", MockExamIssue("total_seconds", "total_mismatch", "total_seconds must equal the sum of section seconds"))
    if "verified" in spec:
        fail("g6", MockExamIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))
    return gates, issues


def assemble_mock_exam(
    spec: Mapping[str, Any], questions: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Assemble the student-facing paper. Answers are never included."""
    by_id = {str(q.get("id")): q for q in questions}
    sections: list[dict[str, Any]] = []
    for section in spec.get("sections", []):
        items = []
        for qid in section.get("question_ids", []):
            question = by_id.get(str(qid))
            items.append(
                {
                    "question_id": str(qid),
                    "question_text": question.get("question_text") if question else None,
                }
            )
        sections.append(
            {"name": section.get("name"), "seconds": section.get("seconds"), "items": items}
        )
    return {
        "id": spec.get("id"),
        "title": spec.get("title"),
        "subject": spec.get("subject"),
        "level": spec.get("level"),
        "total_seconds": spec.get("total_seconds"),
        "sections": sections,
    }


def score_mock_exam(
    spec: Mapping[str, Any],
    questions: list[Mapping[str, Any]],
    answers: Mapping[str, Any],
    *,
    late: bool = False,
) -> dict[str, Any]:
    """Deterministic scoring over the existing graders.

    Deviation from the task book, recorded in ALL_GRAFTS.md: submit_quiz
    is NOT reused because it writes BKT/FSRS. grade_deterministic is
    the single deterministic entry point; grade_math is the fallback
    for math subjects when it returns unsure.
    """
    from services.math_grade import grade_math
    from services.wrongbook_review_service import grade_deterministic

    by_id = {str(q.get("id")): q for q in questions}
    section_results: list[dict[str, Any]] = []
    total_correct = 0
    total_items = 0
    for section in spec.get("sections", []):
        items: list[dict[str, Any]] = []
        correct = 0
        for qid in section.get("question_ids", []):
            question = by_id.get(str(qid))
            answer = answers.get(str(qid), "")
            if question is None or question.get("correct_answer") is None:
                items.append({"question_id": str(qid), "is_correct": None, "verdict": "ungradeable"})
                continue
            verdict, grader = grade_deterministic(str(answer), str(question["correct_answer"]), question.get("subject"))
            if verdict is None and str(question.get("subject") or "").lower() in ("math", "数学", "maths"):
                try:
                    verdict = bool(grade_math(str(answer), str(question["correct_answer"])))
                    grader = "math"
                except Exception:
                    verdict = None
            if verdict is None:
                items.append({"question_id": str(qid), "is_correct": None, "verdict": "unsure", "grader": grader})
            else:
                items.append({"question_id": str(qid), "is_correct": bool(verdict), "verdict": "correct" if verdict else "wrong", "grader": grader})
                correct += 1 if verdict else 0
            total_items += 1
        total_correct += correct
        section_results.append(
            {"name": section.get("name"), "correct": correct, "total": len(section.get("question_ids", [])), "items": items}
        )
    return {
        "id": spec.get("id"),
        "correct": total_correct,
        "total": total_items,
        "score": (total_correct / total_items) if total_items else 0.0,
        "late": late,
        "sections": section_results,
    }


__all__ = ["MockExamIssue", "assemble_mock_exam", "score_mock_exam", "verify_mock_exam_spec"]
