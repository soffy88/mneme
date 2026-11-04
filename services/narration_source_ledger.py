"""Narration source ledger gate (vibe-knowledge G1 method, clean rewrite).

Every factual assertion spoken on screen must have one ledger row: the
assertion, its source, a source tier, and a verbatim quote, plus the shot
it is used in. Disputed assertions must list both sayings, and an
adversarial review record must sign the ledger off. A lesson script with
no ledger, or with a ledger that fails any rule below, must not enter
production rendering.

Only the *structure* is borrowed from the reviewed skill's facts ledger
(one row per assertion, tiered sources, both-sides disputes, a review
record). All wording, identifiers, and rules here are Mneme's own; no
upstream text, prompts, or sample material is copied.

Division of labour with the existing gates (no second label system):
- services/provenance.py owns the three tiers (MATERIAL / SUPPLEMENT /
  GENERATED) and certifies that every reply segment carries one. A
  ledger row consumes one of those tiers; this module does not redefine
  them.
- services/citation_check.py owns reference resolution (a cited KU /
  textbook / figure must really exist) and math-equivalence claims.
  This module does not resolve ids.
- This module owns the per-assertion ledger: source present, tier
  assigned, quote present, disputes listed both sides, review signed.

The ledger travels as structured data inside the lesson spec
(spec["source_ledger"]) and persists in the existing
VideoLessonSpec.spec JSONB column: no new table, no migration.

Gate rules (all fail-closed; every failure lists its cause):
- Ledger present, rows a non-empty list, at most MAX_ROWS rows.
- Row id unique, shaped like L01. Claim non-empty, at most
  MAX_CLAIM_CHARS chars: one row, one atomic assertion.
- shot must be an existing scene index. Every factual shot must have
  at least one row covering it.
- Evidence entries carry a non-empty source, a valid tier, and a
  non-empty verbatim quote of at most MAX_QUOTE_CHARS chars.
- MATERIAL rows need at least one T1/T2 source. SUPPLEMENT rows need
  at least one source. GENERATED rows are framing text: they must carry
  no evidence and status "framing".
- Evidence that is T3-only never supports an on-screen assertion.
- status must match the evidence: "verified" needs a T1 source or two
  T1/T2 sources; "single-source" needs exactly one T1/T2 source;
  "disputed" needs a complete alternative saying plus supporting
  evidence; "framing" is GENERATED-only.
- The same assertion must not appear twice in one shot.
- The adversarial review record must be present, name a reviewer, and
  pass all four checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from services.provenance import ProvenanceLabel
from services.video_lesson import verify_video_lesson

MAX_CLAIM_CHARS = 120
MAX_QUOTE_CHARS = 400
MAX_ROWS = 200
ROW_ID_RE = re.compile(r"^L\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ROW_STATUSES = ("verified", "single-source", "disputed", "framing")
REVIEW_CHECKS = (
    "no_unsourced_assertions",
    "every_row_tiered",
    "disputes_listed_both_sides",
    "quotes_present",
)


class SourceTier(str, Enum):
    """Source tier: how much the cited source can carry."""

    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


TIER_MEANING = {
    SourceTier.T1: "primary source: official textbook or material text, primary document, original paper, official page",
    SourceTier.T2: "authoritative secondary: textbook treatment, encyclopedia entry with citations, mainstream reporting",
    SourceTier.T3: "community lead only: never the sole support of an on-screen assertion",
}


class LedgerIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


class LedgerCheck:
    def __init__(self, issues: list[LedgerIssue], rows_checked: int) -> None:
        self.issues = issues
        self.rows_checked = rows_checked

    @property
    def passed(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class LedgerEvidence:
    """One supporting source for a row: source, tier, verbatim quote."""

    source: str
    tier: SourceTier
    quote: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "tier": self.tier.value, "quote": self.quote}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LedgerEvidence":
        return cls(
            source=str(data["source"]),
            tier=SourceTier(data["tier"]),
            quote=str(data["quote"]),
        )


@dataclass(frozen=True)
class LedgerAlternative:
    """The other saying, when sources disagree: both sayings are listed."""

    claim: str
    source: str
    tier: SourceTier
    quote: str

    def to_dict(self) -> dict[str, str]:
        return {
            "claim": self.claim,
            "source": self.source,
            "tier": self.tier.value,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LedgerAlternative":
        return cls(
            claim=str(data["claim"]),
            source=str(data["source"]),
            tier=SourceTier(data["tier"]),
            quote=str(data["quote"]),
        )


@dataclass(frozen=True)
class LedgerRow:
    """One ledger row: one atomic assertion used in one shot."""

    id: str
    claim: str
    shot: int
    label: ProvenanceLabel
    evidence: list[LedgerEvidence] = field(default_factory=list)
    status: str = "single-source"
    alternative: Optional[LedgerAlternative] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "claim": self.claim,
            "shot": self.shot,
            "label": self.label.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
        }
        if self.alternative is not None:
            out["alternative"] = self.alternative.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LedgerRow":
        alternative = data.get("alternative")
        return cls(
            id=str(data["id"]),
            claim=str(data["claim"]),
            shot=int(data["shot"]),
            label=ProvenanceLabel(data["label"]),
            evidence=[LedgerEvidence.from_dict(e) for e in data.get("evidence", [])],
            status=str(data.get("status", "single-source")),
            alternative=LedgerAlternative.from_dict(alternative) if alternative is not None else None,
        )


@dataclass(frozen=True)
class AdversarialReview:
    """Adversarial review record: a named reviewer signs all four checks."""

    reviewer: str
    checks: dict[str, bool]
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"reviewer": self.reviewer, "checks": dict(self.checks), "notes": self.notes}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdversarialReview":
        return cls(
            reviewer=str(data["reviewer"]),
            checks={str(k): bool(v) for k, v in dict(data["checks"]).items()},
            notes=str(data.get("notes", "")),
        )


@dataclass(frozen=True)
class SourceLedger:
    """A full ledger: rows plus the adversarial review record."""

    rows: list[LedgerRow]
    review: AdversarialReview
    as_of: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rows": [r.to_dict() for r in self.rows],
            "review": self.review.to_dict(),
        }
        if self.as_of is not None:
            out["as_of"] = self.as_of
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceLedger":
        return cls(
            rows=[LedgerRow.from_dict(r) for r in data["rows"]],
            review=AdversarialReview.from_dict(data["review"]),
            as_of=data.get("as_of"),
        )


def ledger_to_dict(ledger: SourceLedger) -> dict[str, Any]:
    """Serialize a ledger to plain JSON-safe data."""
    return ledger.to_dict()


def ledger_from_dict(data: Mapping[str, Any]) -> SourceLedger:
    """Parse serialized ledger data. Raises ValueError on bad tiers/labels."""
    return SourceLedger.from_dict(data)


def attach_ledger(spec: Mapping[str, Any], ledger: SourceLedger) -> dict[str, Any]:
    """Return a copy of a lesson spec carrying the ledger under source_ledger.

    The input spec is not mutated. Nested scene/caption lists are shared
    with the input; only the top-level mapping is copied.
    """
    out = dict(spec)
    out["source_ledger"] = ledger.to_dict()
    return out


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_evidence(
    evidence: object, field: str, issues: list[LedgerIssue]
) -> list[dict[str, Any]]:
    """Validate one row's evidence list; return the usable entries."""
    usable: list[dict[str, Any]] = []
    if not isinstance(evidence, list):
        issues.append(LedgerIssue(field, "bad_evidence", "evidence must be a list"))
        return usable
    for pos, entry in enumerate(evidence):
        entry_field = f"{field}[{pos}]"
        if not isinstance(entry, Mapping):
            issues.append(LedgerIssue(entry_field, "not_an_object", "evidence entry must be an object"))
            continue
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            issues.append(LedgerIssue(f"{entry_field}.source", "empty_source", "evidence source must be a non-empty string"))
        tier_raw = entry.get("tier")
        tier: Optional[SourceTier] = None
        if tier_raw not in {t.value for t in SourceTier}:
            issues.append(LedgerIssue(f"{entry_field}.tier", "bad_tier", "evidence tier must be one of T1, T2, T3"))
        else:
            tier = SourceTier(tier_raw)
        quote = entry.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            issues.append(LedgerIssue(f"{entry_field}.quote", "missing_quote", "evidence quote must be a non-empty verbatim excerpt"))
        elif len(quote) > MAX_QUOTE_CHARS:
            issues.append(LedgerIssue(f"{entry_field}.quote", "quote_too_long", "evidence quote exceeds the length bound"))
        if tier is not None and isinstance(source, str) and source.strip():
            usable.append({"source": source, "tier": tier})
    return usable


def _check_alternative(
    alternative: object, field: str, issues: list[LedgerIssue]
) -> bool:
    """A disputed row's alternative saying must be complete. Returns ok."""
    if not isinstance(alternative, Mapping):
        issues.append(LedgerIssue(field, "dispute_incomplete", "disputed rows must carry a complete alternative saying"))
        return False
    ok = True
    for key in ("claim", "source", "quote"):
        value = alternative.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                LedgerIssue(f"{field}.{key}", "dispute_incomplete", f"alternative {key} must be a non-empty string")
            )
            ok = False
    quote = alternative.get("quote")
    if isinstance(quote, str) and len(quote) > MAX_QUOTE_CHARS:
        issues.append(LedgerIssue(f"{field}.quote", "quote_too_long", "alternative quote exceeds the length bound"))
        ok = False
    if alternative.get("tier") not in {t.value for t in SourceTier}:
        issues.append(LedgerIssue(f"{field}.tier", "bad_tier", "alternative tier must be one of T1, T2, T3"))
        ok = False
    return ok


def _check_row(
    row: object,
    pos: int,
    scene_count: int,
    seen_ids: set[str],
    seen_assertions: set[tuple[str, int]],
    issues: list[LedgerIssue],
) -> None:
    field = f"rows[{pos}]"
    if not isinstance(row, Mapping):
        issues.append(LedgerIssue(field, "not_an_object", "ledger row must be an object"))
        return
    row_id = row.get("id")
    if not isinstance(row_id, str) or not ROW_ID_RE.match(row_id):
        issues.append(LedgerIssue(f"{field}.id", "bad_row_id", "row id must look like L01"))
    elif row_id in seen_ids:
        issues.append(LedgerIssue(f"{field}.id", "duplicate_row_id", "row id must be unique"))
    elif isinstance(row_id, str):
        seen_ids.add(row_id)
    claim = row.get("claim")
    claim_ok = isinstance(claim, str) and bool(claim.strip())
    if not claim_ok:
        issues.append(LedgerIssue(f"{field}.claim", "empty_claim", "claim must be a non-empty string"))
    elif len(claim) > MAX_CLAIM_CHARS:
        issues.append(LedgerIssue(f"{field}.claim", "claim_too_long", "claim exceeds the length bound"))
    shot = row.get("shot")
    shot_ok = _is_int(shot) and 0 <= shot < scene_count
    if not _is_int(shot):
        issues.append(LedgerIssue(f"{field}.shot", "bad_shot", "shot must be an integer scene index"))
    elif not 0 <= shot < scene_count:
        issues.append(LedgerIssue(f"{field}.shot", "dangling_shot", "shot does not resolve to an existing scene"))
    if claim_ok and shot_ok:
        key = (" ".join(str(claim).split()).casefold(), shot)
        if key in seen_assertions:
            issues.append(LedgerIssue(field, "duplicate_assertion", "the same assertion must not appear twice in one shot"))
        else:
            seen_assertions.add(key)
    label_raw = row.get("label")
    label_ok = label_raw in {item.value for item in ProvenanceLabel}
    if not label_ok:
        issues.append(
            LedgerIssue(f"{field}.label", "bad_label", "label must be one of the provenance tiers (material, supplement, generated)")
        )
    status = row.get("status")
    if status not in ROW_STATUSES:
        issues.append(LedgerIssue(f"{field}.status", "bad_status", "status must be verified, single-source, disputed, or framing"))
        return
    evidence = row.get("evidence", [])
    usable = _check_evidence(evidence, f"{field}.evidence", issues)
    strong = [e for e in usable if e["tier"] in (SourceTier.T1, SourceTier.T2)]
    has_t1 = any(e["tier"] is SourceTier.T1 for e in usable)
    if usable and not strong:
        issues.append(
            LedgerIssue(f"{field}.evidence", "t3_only_unsupported", "T3-only evidence never supports an on-screen assertion")
        )
    alternative = row.get("alternative")
    if status == "disputed":
        _check_alternative(alternative, f"{field}.alternative", issues)
    elif alternative is not None:
        issues.append(
            LedgerIssue(f"{field}.alternative", "alternative_without_dispute", "only disputed rows carry an alternative saying")
        )
    if not label_ok:
        return
    if label_raw == ProvenanceLabel.GENERATED.value:
        if usable or (isinstance(evidence, list) and evidence):
            issues.append(
                LedgerIssue(f"{field}.evidence", "generated_must_not_cite", "generated framing rows must not carry evidence")
            )
        if status != "framing":
            issues.append(
                LedgerIssue(f"{field}.status", "generated_needs_framing_status", "generated rows must use status framing")
            )
        return
    if status == "framing":
        issues.append(
            LedgerIssue(f"{field}.status", "framing_status_needs_generated", "framing status is for generated rows only")
        )
    if not usable:
        issues.append(LedgerIssue(f"{field}.evidence", "missing_evidence", "sourced rows need at least one evidence entry"))
        return
    if label_raw == ProvenanceLabel.MATERIAL.value and not strong:
        issues.append(
            LedgerIssue(f"{field}.evidence", "material_needs_strong_source", "MATERIAL rows need at least one T1/T2 source")
        )
    if status == "verified" and not (has_t1 or len(strong) >= 2):
        issues.append(
            LedgerIssue(f"{field}.status", "status_evidence_mismatch", "verified needs a T1 source or two T1/T2 sources")
        )
    if status == "single-source" and not (len(usable) == 1 and strong):
        issues.append(
            LedgerIssue(f"{field}.status", "status_evidence_mismatch", "single-source needs exactly one T1/T2 source")
        )
    if status == "disputed" and not strong:
        issues.append(
            LedgerIssue(f"{field}.status", "status_evidence_mismatch", "disputed rows need supporting T1/T2 evidence")
        )


def _check_review(review: object, issues: list[LedgerIssue]) -> None:
    if not isinstance(review, Mapping):
        issues.append(LedgerIssue("review", "missing_review", "an adversarial review record is required"))
        return
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        issues.append(LedgerIssue("review.reviewer", "bad_reviewer", "reviewer must be a non-empty string"))
    checks = review.get("checks")
    if not isinstance(checks, Mapping):
        issues.append(LedgerIssue("review.checks", "review_incomplete", "review checks must be an object"))
        return
    for key in REVIEW_CHECKS:
        if key not in checks:
            issues.append(LedgerIssue(f"review.checks.{key}", "review_check_missing", "review check is missing"))
        elif checks[key] is not True:
            issues.append(LedgerIssue(f"review.checks.{key}", "review_check_failed", "review check did not pass"))
    notes = review.get("notes")
    if notes is not None and not isinstance(notes, str):
        issues.append(LedgerIssue("review.notes", "bad_notes", "review notes must be a string"))


def verify_source_ledger(
    ledger: object,
    *,
    scene_count: int,
    factual_shots: Optional[Sequence[int]] = None,
) -> LedgerCheck:
    """Gate a source ledger. Fail-closed: every failure lists its cause.

    factual_shots, when given, lists the scene indices whose narration
    carries factual assertions; each must have at least one ledger row.
    When omitted, no coverage requirement is applied (the lesson-level
    adapter defaults to every scene).
    """
    issues: list[LedgerIssue] = []
    if not _is_int(scene_count) or scene_count <= 0:
        return LedgerCheck(
            [LedgerIssue("scene_count", "bad_scene_count", "scene_count must be a positive integer")], 0
        )
    if not isinstance(ledger, Mapping):
        return LedgerCheck([LedgerIssue("", "not_an_object", "ledger must be an object")], 0)
    as_of = ledger.get("as_of")
    if as_of is not None and (not isinstance(as_of, str) or not DATE_RE.match(as_of)):
        issues.append(LedgerIssue("as_of", "bad_as_of", "as_of must look like YYYY-MM-DD"))
    rows = ledger.get("rows")
    if not isinstance(rows, list) or not rows:
        issues.append(LedgerIssue("rows", "empty_ledger", "ledger rows must be a non-empty list"))
        rows = []
    if len(rows) > MAX_ROWS:
        issues.append(LedgerIssue("rows", "too_many_rows", "ledger rows exceed the bound"))
    seen_ids: set[str] = set()
    seen_assertions: set[tuple[str, int]] = set()
    covered: set[int] = set()
    for pos, row in enumerate(rows):
        _check_row(row, pos, scene_count, seen_ids, seen_assertions, issues)
        if isinstance(row, Mapping) and _is_int(row.get("shot")) and 0 <= row["shot"] < scene_count:
            covered.add(row["shot"])
    _check_review(ledger.get("review"), issues)
    if factual_shots is not None:
        for shot in factual_shots:
            if not _is_int(shot) or not 0 <= shot < scene_count:
                issues.append(LedgerIssue("factual_shots", "bad_factual_shot", "factual shot must be an existing scene index"))
            elif shot not in covered:
                issues.append(
                    LedgerIssue(f"shots[{shot}]", "shot_uncovered", "factual shot has no ledger row covering it")
                )
    return LedgerCheck(issues, len(rows))


def verify_lesson_source_ledger(
    spec: Mapping[str, Any],
    *,
    factual_shots: Optional[Sequence[int]] = None,
) -> LedgerCheck:
    """Gate the source_ledger carried by a lesson spec. Fail-closed.

    A spec with no source_ledger fails: narration without a ledger must
    not enter production rendering. When factual_shots is omitted, every
    scene counts as factual (the video-lesson contract requires
    narration text per scene).
    """
    if not isinstance(spec, Mapping):
        return LedgerCheck([LedgerIssue("", "not_an_object", "spec must be an object")], 0)
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return LedgerCheck([LedgerIssue("scenes", "missing_scenes", "scenes must be a non-empty list")], 0)
    ledger = spec.get("source_ledger")
    if ledger is None:
        return LedgerCheck(
            [LedgerIssue("source_ledger", "missing_ledger", "lesson scripts must carry a source ledger")], 0
        )
    shots = factual_shots if factual_shots is not None else list(range(len(scenes)))
    return verify_source_ledger(ledger, scene_count=len(scenes), factual_shots=shots)


def certify_lesson_script(
    spec: Mapping[str, Any],
    known_ku_ids: Optional[set[str]] = None,
    *,
    factual_shots: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Certify a lesson script for production: video gates plus ledger gate.

    Returns {"passed", "video_lesson": {...}, "source_ledger": {...}}.
    Either side failing fails the whole script; no side is skipped.
    """
    video = verify_video_lesson(spec, known_ku_ids)
    ledger = verify_lesson_source_ledger(spec, factual_shots=factual_shots)
    return {
        "passed": video.passed and ledger.passed,
        "video_lesson": {
            "passed": video.passed,
            "issues": [issue.to_dict() for issue in video.issues],
        },
        "source_ledger": {
            "passed": ledger.passed,
            "issues": [issue.to_dict() for issue in ledger.issues],
        },
    }


__all__ = [
    "MAX_CLAIM_CHARS",
    "MAX_QUOTE_CHARS",
    "MAX_ROWS",
    "REVIEW_CHECKS",
    "ROW_STATUSES",
    "AdversarialReview",
    "LedgerAlternative",
    "LedgerCheck",
    "LedgerEvidence",
    "LedgerIssue",
    "LedgerRow",
    "SourceLedger",
    "SourceTier",
    "TIER_MEANING",
    "attach_ledger",
    "certify_lesson_script",
    "ledger_from_dict",
    "ledger_to_dict",
    "verify_lesson_source_ledger",
    "verify_source_ledger",
]
