"""Citation verification + review eligibility gate (DeepTutor Guided
Learning method, clean rewrite).

Two pure surfaces, no LLM in the default path:

- check_citations: every cited reference must resolve to a real KU id,
  textbook id, or figure object key. Math-equivalence claims are checked
  with the deterministic math_grade.grade_math only. An optional
  qualitative callback may be injected by callers; when absent, that
  dimension reports "not_run" instead of being invented.
- eligible_review_scope: review work must stay inside the set the
  mastery gate + path lock allow, via the existing read-only
  check_path_lock. Nothing here writes mastery or schedules anything.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from services.math_grade import grade_math
from services.path_lock_service import check_path_lock

FIGURE_KEY_RE = re.compile(r"^figures/[A-Za-z0-9_.\-]+/p\d+_\d+\.png$")

REF_KINDS = ("ku", "textbook", "figure")


class CitationIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def _check_refs(
    refs: object,
    field: str,
    known_ku_ids: Optional[set[str]],
    known_textbook_ids: Optional[set[str]],
) -> list[CitationIssue]:
    issues: list[CitationIssue] = []
    if not isinstance(refs, list) or not refs:
        return [CitationIssue(field, "missing_refs", "segment must cite at least one reference")]
    for pos, ref in enumerate(refs):
        ref_field = f"{field}[{pos}]"
        if not isinstance(ref, dict):
            issues.append(CitationIssue(ref_field, "bad_ref", "reference must be an object"))
            continue
        kind = ref.get("kind")
        ref_id = ref.get("id")
        if kind not in REF_KINDS:
            issues.append(CitationIssue(ref_field, "bad_ref_kind", "reference kind must be ku, textbook, or figure"))
            continue
        if not isinstance(ref_id, str) or not ref_id:
            issues.append(CitationIssue(ref_field, "bad_ref_id", "reference id must be a non-empty string"))
            continue
        if kind == "ku":
            if known_ku_ids is None:
                issues.append(CitationIssue(ref_field, "unknown_ku_set", "KU references cannot be verified without a known set"))
            elif ref_id not in known_ku_ids:
                issues.append(CitationIssue(ref_field, "unknown_ku", "KU reference does not exist"))
        elif kind == "textbook":
            if known_textbook_ids is None:
                issues.append(CitationIssue(ref_field, "unknown_textbook_set", "textbook references cannot be verified without a known set"))
            elif ref_id not in known_textbook_ids:
                issues.append(CitationIssue(ref_field, "unknown_textbook", "textbook reference does not exist"))
        elif kind == "figure":
            if not FIGURE_KEY_RE.match(ref_id):
                issues.append(CitationIssue(ref_field, "bad_figure_key", "figure key must look like figures/<doc>/p<page>_<n>.png"))
    return issues


def _check_math(
    math: object, field: str, qualitative: Optional[Callable[[str, list[dict]], Optional[bool]]]
) -> tuple[list[CitationIssue], str]:
    """Math dimension: deterministic equivalence only.

    Returns (issues, state) where state is one of passed / failed /
    unverifiable / not_applicable / not_run.
    """
    if math is None:
        return [], "not_applicable"
    if not isinstance(math, dict):
        return [CitationIssue(field, "bad_math", "math must be an object")], "failed"
    claim = math.get("claim")
    source = math.get("source")
    if not isinstance(claim, str) or not claim.strip():
        return [CitationIssue(field, "bad_math_claim", "math claim must be a non-empty string")], "failed"
    if not isinstance(source, str) or not source.strip():
        return [CitationIssue(field, "bad_math_source", "math source must be a non-empty string")], "failed"
    try:
        equivalent = grade_math(claim, source)
    except Exception:
        return [CitationIssue(field, "math_unverifiable", "math equivalence could not be evaluated")], "unverifiable"
    if not equivalent:
        return [CitationIssue(field, "math_not_equivalent", "math claim is not equivalent to the source")], "failed"
    if qualitative is not None:
        try:
            verdict = qualitative(claim, [])
        except Exception:
            return [CitationIssue(field, "qualitative_error", "qualitative check raised")], "unverifiable"
        if verdict is False:
            return [CitationIssue(field, "qualitative_mismatch", "qualitative check rejected the claim")], "failed"
        if verdict is None:
            return [], "not_run"
    return [], "passed"


def check_citations(
    segments: Sequence[Mapping[str, Any]],
    *,
    known_ku_ids: Optional[set[str]] = None,
    known_textbook_ids: Optional[set[str]] = None,
    qualitative: Optional[Callable[[str, list[dict]], Optional[bool]]] = None,
) -> dict[str, Any]:
    """Verify each answer segment's citations. Fail-closed on unknown sets."""
    if not isinstance(segments, list) or not segments:
        return {
            "passed": False,
            "issues": [CitationIssue("", "empty_segments", "segments must be a non-empty list").to_dict()],
            "segments": [],
        }
    checked: list[dict[str, Any]] = []
    all_passed = True
    for pos, segment in enumerate(segments):
        field = f"segments[{pos}]"
        if not isinstance(segment, dict):
            checked.append({"index": pos, "verdict": "fail", "issues": [CitationIssue(field, "not_an_object", "segment must be an object").to_dict()], "math": "not_applicable"})
            all_passed = False
            continue
        issues = _check_refs(segment.get("refs"), f"{field}.refs", known_ku_ids, known_textbook_ids)
        math_issues, math_state = _check_math(segment.get("math"), f"{field}.math", qualitative)
        issues.extend(math_issues)
        has_fail = any(i.code not in ("math_unverifiable", "qualitative_error") for i in issues)
        if has_fail:
            verdict = "fail"
        elif issues:
            verdict = "unverifiable"
        else:
            verdict = "pass"
        if verdict != "pass":
            all_passed = False
        checked.append(
            {
                "index": pos,
                "text": segment.get("text"),
                "verdict": verdict,
                "issues": [i.to_dict() for i in issues],
                "math": math_state,
            }
        )
    return {"passed": all_passed, "segments": checked, "issues": []}


async def eligible_review_scope(
    db: AsyncSession, student_id: uuid.UUID, ku_ids: Sequence[str]
) -> dict[str, Any]:
    """Split ku_ids into allowed/denied by the existing path-lock gate.

    Read-only. check_path_lock fails open on internal errors by design;
    its reason strings are surfaced verbatim so callers can tell why.
    """
    allowed: list[str] = []
    denied: list[dict[str, str]] = []
    seen: set[str] = set()
    for ku_id in ku_ids:
        if ku_id in seen:
            continue
        seen.add(ku_id)
        decision = await check_path_lock(db, student_id, ku_id)
        if decision.allowed:
            allowed.append(ku_id)
        else:
            denied.append({"ku_id": ku_id, "reason": str(decision.reason)})
    return {"allowed": allowed, "denied": denied}


__all__ = ["CitationIssue", "FIGURE_KEY_RE", "check_citations", "eligible_review_scope"]
