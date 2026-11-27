"""AI Physics Assistant G1-G4 contracts (clean rewrite, gates only).

Soffy approved 2026-11-28 ("G1-G4 four contracts"). This module is
*contracts*, not content: no question, answer, student record, or
knowledge-point text is imported from
ai-physics-assistant.app.workbuddy.host, which has no licence, no
provenance mechanism, and no public diagnostic rules. What was borrowed
is only the *shape* of the four gaps the deep audit found
(files/ai-physics-assistant深审与Mneme对照.md, §5.2 and §8):

- G1 (A): content admission for high-school physics questions/KUs.
- G2 (A): mastery / weak-point definition contract.
- G3 (B): common-wrong-question aggregation contract.
- G4 (B): data-import pipeline contract.

Design rules, all fail-closed (every failure lists its cause):

- Pure functions: no DB, no network, no LLM. Tests run without a
  database, like services/interactive_page.py.
- Zero migration: contracts validate payloads in memory; nothing here
  creates a table or moves EXPECTED_MIGRATION_HEAD (still phy1a2b3c4d5e).
- Reuse, do not re-invent: G1 routes the source ledger through
  services.narration_source_ledger.verify_source_ledger, references
  through services.citation_check.check_citations, and numeric
  recomputation through the Atlas discipline (a model_ref must name a
  registered Atlas model, or an independent recomputation must be
  evidenced). Thresholds come from services.learner_model (GATE /
  MASTERED), the single source of mastery thresholds.
- G2 forbids the exact ambiguity the site showed: its mastery (59.5%)
  equalled its accuracy (59.5%) with no formula anywhere. Here mastery
  and accuracy are always reported as two separate numbers, mastery
  must come from BKT or FSRS inference (never from raw accuracy), and
  the computation method must be named.
- G3 default minimum sample is 5 (see MIN_COMMON_ERROR_SAMPLE): the
  site published "common wrong questions" from as few as 4 attempts,
  and its denominator changed between checks. Records below the
  minimum are withheld, not published with a caveat.
- G4 requires both a dedup key and the existing-key set (unknown set
  fails, like citation_check's unknown_ku_set), and a knowledge-point
  match rule for every row; fuzzy matches need a named human reviewer.
  Student / answer-record import is OFF by default.

Decisions taken inside already-agreed principles (fail-closed), stated
plainly rather than hidden: MIN_COMMON_ERROR_SAMPLE = 5,
MIN_EVIDENCE_N = 5 (a mastery label needs at least 5 attempts of
evidence), MAX_IMPORT_ROWS = 500.
"""

from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Optional, Sequence

from services.citation_check import check_citations
from services.learner_model import GATE, MASTERED
from services.narration_source_ledger import verify_source_ledger

__all__ = [
    "ATLAS_MODEL_NAMES",
    "GATE",
    "IMPORT_TYPES",
    "MASTERED",
    "MAX_IMPORT_ROWS",
    "MIN_COMMON_ERROR_SAMPLE",
    "MIN_EVIDENCE_N",
    "QUESTION_TYPES",
    "TEMPLATE_FIELDS",
    "TYPICAL_ERROR_CATEGORIES",
    "WEAK_ROOTS_KINDS",
    "aggregate_common_errors",
    "compute_mastery_snapshot",
    "dedup_key_for_row",
    "resolve_weak_roots_kind",
    "verify_import_batch",
    "verify_physics_content_admission",
    "weak_roots_namespace",
]

# Fail-closed defaults (decisions, see module docstring).
MIN_COMMON_ERROR_SAMPLE = 5
MIN_EVIDENCE_N = 5
MAX_IMPORT_ROWS = 500

ATLAS_MODEL_NAMES = frozenset({"projectile_motion", "pendulum_small_angle"})
CALCULATION_TYPES = frozenset({"calculation", "compute", "problem_solving"})
QUESTION_TYPES = frozenset(
    {
        "single_choice",
        "multiple_choice",
        "true_false",
        "fill_blank",
        "calculation",
        "compute",
        "problem_solving",
        "short_answer",
    }
)
IMAGE_ONLY_MARKERS = ("公式图", "formula_image", "公式图片")
FIGURE_REF_MARKERS = ("如图", "下图", "题图", "图中")
HTML_ENTITY_LEAK_RE = re.compile(r"&(gt|lt|amp|quot);")

TYPICAL_ERROR_CATEGORIES = (
    "concept_confusion",
    "condition_misread",
    "method_error",
    "computation_error",
    "unit_error",
    "other",
)
IDENTIFIABLE_FIELDS = (
    "student_id",
    "student_name",
    "student_no",
    "name",
    "answers",
    "student_answers",
    "per_student",
)

IMPORT_TYPES = ("paper", "question", "answer_record", "student", "knowledge_point")
PII_IMPORT_TYPES = ("student", "answer_record")

TEMPLATE_FIELDS: dict[str, tuple[str, ...]] = {
    # Field names follow the site's visible CSV columns where the site
    # showed any (paper / question / answer_record); the student and
    # knowledge_point templates are Mneme-defined, because the site
    # showed no template for either.
    "paper": (
        "paper_name",
        "grade",
        "textbook_version",
        "total_score",
        "exam_time",
        "question_no",
        "stem",
        "question_type",
        "options",
        "answer",
        "difficulty",
        "kp_ids",
        "ku_name",
    ),
    "question": (
        "stem",
        "question_type",
        "options_a",
        "options_b",
        "options_c",
        "options_d",
        "answer",
        "difficulty",
        "paper",
        "chapter",
        "knowledge_points",
        "kp_ids",
    ),
    "answer_record": (
        "student_name",
        "paper",
        "question_no",
        "answer",
        "is_correct",
        "answered_at",
    ),
    "student": ("student_name", "student_no", "grade", "class_name"),
    "knowledge_point": (
        "kp_id",
        "name",
        "chapter",
        "textbook_version",
        "parent_kp_id",
    ),
}

WEAK_ROOTS_KINDS = {
    # The two weak_roots in Mneme are different things sharing a name.
    # Every payload must name which one it is; an unnamed one fails.
    "cognitive_mastery": (
        "cognitive_service.weakness_roots",
        "mastery attribution: weak KUs traced up the prerequisite graph",
    ),
    "prereq_diagnosis": (
        "prereq_diagnosis_service._report",
        "answer-trace attribution: weak roots from a diagnosis session",
    ),
}


class ContractIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _norm_text(value: object) -> str:
    return " ".join(str(value or "").split()).lower()


def _issues_to_dicts(issues: list[ContractIssue]) -> list[dict[str, str]]:
    return [i.to_dict() for i in issues]


# ── G1: content admission ──────────────────────────────────────────────────


def _default_ledger_check(spec: Mapping[str, Any]) -> SimpleNamespace:
    """Ledger gate for one question: the question is a single shot.

    Reuses verify_source_ledger with scene_count=1; a ledger row must
    cover shot 0 and the adversarial review must pass. A spec with no
    source_ledger fails here, exactly like a lesson script without one.
    """
    ledger = spec.get("source_ledger")
    if ledger is None:
        return SimpleNamespace(
            passed=False,
            issues=[
                {
                    "field": "source_ledger",
                    "code": "missing_ledger",
                    "message": "physics content must carry a source ledger",
                }
            ],
        )
    check = verify_source_ledger(ledger, scene_count=1, factual_shots=[0])
    return SimpleNamespace(
        passed=check.passed, issues=[i.to_dict() for i in check.issues]
    )


def _check_formulas(spec: Mapping[str, Any], issues: list[ContractIssue]) -> str:
    """Formulas must be recomputable text, never image-only.

    The audited site rendered most teaching-desk formulas as images and
    68 of 69 failed to load in one viewport, leaving stems unreadable;
    raw LaTeX with leaked HTML entities (&gt;) is also a failure.
    """
    stem = spec.get("stem") or ""
    options = spec.get("options") or {}
    texts = [stem]
    if isinstance(options, Mapping):
        texts.extend(str(v) for v in options.values())
    elif isinstance(options, Sequence):
        texts.extend(str(v) for v in options)
    joined = "\n".join(texts)
    if HTML_ENTITY_LEAK_RE.search(joined):
        issues.append(
            ContractIssue(
                "formulas",
                "unrendered_markup",
                "stem or options contain leaked HTML entities: LaTeX was not rendered",
            )
        )
        return "fail"
    for marker in IMAGE_ONLY_MARKERS:
        if marker in joined:
            issues.append(
                ContractIssue(
                    "formulas",
                    "image_only_formula",
                    "formula is present only as an image; recomputable text is required",
                )
            )
            return "fail"
    formulas = spec.get("formulas")
    if formulas is None:
        return "not_applicable"
    if not isinstance(formulas, list):
        issues.append(
            ContractIssue("formulas", "bad_formulas", "formulas must be a list")
        )
        return "fail"
    state = "pass"
    for pos, formula in enumerate(formulas):
        field = f"formulas[{pos}]"
        if not isinstance(formula, Mapping):
            issues.append(
                ContractIssue(field, "bad_formula", "formula must be an object")
            )
            state = "fail"
            continue
        if formula.get("image_only") is True or not _non_empty_str(formula.get("text")):
            issues.append(
                ContractIssue(
                    field,
                    "image_only_formula",
                    "every formula needs non-empty recomputable text",
                )
            )
            state = "fail"
    return state


def _check_figures(spec: Mapping[str, Any], issues: list[ContractIssue]) -> str:
    """A missing question figure fails admission: the stem is incomplete.

    The audited site left a question figure failing to load at the same
    position across two checks; a stem that refers to a figure ("如图")
    with no usable figure attached is the same failure.
    """
    stem = spec.get("stem") or ""
    refers_to_figure = any(m in str(stem) for m in FIGURE_REF_MARKERS)
    images = spec.get("images")
    if images is None:
        if refers_to_figure:
            issues.append(
                ContractIssue(
                    "images",
                    "missing_figure",
                    "stem refers to a figure but no figure is attached",
                )
            )
            return "fail"
        return "not_applicable"
    if not isinstance(images, list):
        issues.append(ContractIssue("images", "bad_images", "images must be a list"))
        return "fail"
    state = "pass"
    for pos, image in enumerate(images):
        field = f"images[{pos}]"
        if not isinstance(image, Mapping):
            issues.append(ContractIssue(field, "bad_image", "image must be an object"))
            state = "fail"
            continue
        status = image.get("status")
        if status != "ok":
            issues.append(
                ContractIssue(
                    field,
                    "missing_figure",
                    "question figure status must be ok, got "
                    + ("missing status" if status is None else str(status)),
                )
            )
            state = "fail"
    return state


def _check_atlas(
    spec: Mapping[str, Any],
    issues: list[ContractIssue],
    atlas_check: Optional[Callable[[Mapping[str, Any]], Any]],
) -> str:
    """Calculation questions: the answer must be recomputed, not asserted.

    Atlas discipline: a model_ref must name a registered Atlas model, or
    an independent recomputation must be evidenced. Non-calculation
    questions do not need this gate.
    """
    qtype = spec.get("question_type")
    needs_recompute = (
        qtype in CALCULATION_TYPES or spec.get("requires_recompute") is True
    )
    if not needs_recompute:
        return "not_applicable"
    if atlas_check is not None:
        check = atlas_check(spec)
        check_issues = getattr(check, "issues", []) or []
        for issue in check_issues:
            if isinstance(issue, Mapping):
                issues.append(
                    ContractIssue(
                        str(issue.get("field", "atlas")),
                        str(issue.get("code", "atlas_failed")),
                        str(issue.get("message", "Atlas check failed")),
                    )
                )
            else:
                issues.append(ContractIssue("atlas", "atlas_failed", str(issue)))
        return "pass" if getattr(check, "passed", False) else "fail"
    answer = spec.get("answer")
    if not isinstance(answer, Mapping):
        issues.append(
            ContractIssue(
                "answer",
                "missing_answer",
                "calculation question needs an answer object",
            )
        )
        return "fail"
    if answer.get("recomputed") is not True:
        issues.append(
            ContractIssue(
                "answer",
                "not_recomputed",
                "calculation answer must be recomputed, not only asserted",
            )
        )
        return "fail"
    method = answer.get("recompute_method")
    if method == "atlas_model":
        model_ref = answer.get("model_ref")
        if model_ref not in ATLAS_MODEL_NAMES:
            issues.append(
                ContractIssue(
                    "answer.model_ref",
                    "unknown_atlas_model",
                    "atlas_model recomputation needs a registered Atlas model_ref",
                )
            )
            return "fail"
        return "pass"
    if method == "independent_recompute":
        if not _non_empty_str(answer.get("recompute_evidence")):
            issues.append(
                ContractIssue(
                    "answer",
                    "missing_recompute_evidence",
                    "independent recomputation needs named evidence (second method and result)",
                )
            )
            return "fail"
        return "pass"
    issues.append(
        ContractIssue(
            "answer.recompute_method",
            "bad_recompute_method",
            "recompute_method must be atlas_model or independent_recompute",
        )
    )
    return "fail"


def verify_physics_content_admission(
    spec: object,
    *,
    known_ku_ids: Optional[set[str]] = None,
    known_textbook_ids: Optional[set[str]] = None,
    ledger_check: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    atlas_check: Optional[Callable[[Mapping[str, Any]], Any]] = None,
) -> dict[str, Any]:
    """G1 gate: admit one physics question / KU into Mneme, or refuse it.

    Gates (all fail-closed; every failure lists its cause):
    - ledger: source ledger via verify_source_ledger (scene_count=1);
      a missing ledger, or no injected ledger_check, fails as
      ledger_gate_unavailable / missing_ledger.
    - citations: spec["refs"] must resolve through check_citations;
      unknown KU / textbook sets fail closed.
    - curriculum: mapping to a known textbook + chapter + standard,
      plus a named human reviewer.
    - formulas: recomputable text only; image-only formulas and leaked
      HTML entities fail.
    - figures: every attached figure must load (status ok); a stem
      referring to a figure with none attached fails.
    - atlas: calculation questions need a recomputed answer (Atlas
      model or evidenced independent recomputation).
    - labels: the knowledge-point label must be human-reviewed and
      match the question's ku_id. The audited site mislabelled
      questions widely (e.g. a Lenz's-law question labelled
      "energy conservation"); an unreviewed label fails admission.
    """
    issues: list[ContractIssue] = []
    gates: dict[str, str] = {}
    if not isinstance(spec, Mapping):
        return {
            "passed": False,
            "gates": {"spec": "fail"},
            "issues": [
                ContractIssue(
                    "spec", "not_an_object", "spec must be an object"
                ).to_dict()
            ],
        }

    # Ledger.
    if ledger_check is None:
        ledger_check = _default_ledger_check
    check = ledger_check(spec)
    check_issues = getattr(check, "issues", []) or []
    for issue in check_issues:
        if isinstance(issue, Mapping):
            issues.append(
                ContractIssue(
                    str(issue.get("field", "source_ledger")),
                    str(issue.get("code", "ledger_failed")),
                    str(issue.get("message", "source ledger check failed")),
                )
            )
        else:
            issues.append(ContractIssue("source_ledger", "ledger_failed", str(issue)))
    gates["ledger"] = "pass" if getattr(check, "passed", False) else "fail"

    # Citations (refs must resolve; unknown sets fail closed).
    refs = spec.get("refs")
    segments = [{"text": spec.get("stem") or "", "refs": refs}]
    citation = check_citations(
        segments, known_ku_ids=known_ku_ids, known_textbook_ids=known_textbook_ids
    )
    for segment in citation.get("segments", []):
        for issue in segment.get("issues", []):
            issues.append(
                ContractIssue(
                    str(issue.get("field", "refs")),
                    str(issue.get("code", "citation_failed")),
                    str(issue.get("message", "citation check failed")),
                )
            )
    gates["citations"] = "pass" if citation.get("passed") else "fail"

    # Curriculum mapping + human review.
    mapping = spec.get("curriculum_mapping")
    curriculum_ok = True
    if not isinstance(mapping, Mapping):
        issues.append(
            ContractIssue(
                "curriculum_mapping",
                "missing_mapping",
                "content needs a curriculum mapping (textbook, chapter, standard)",
            )
        )
        curriculum_ok = False
    else:
        if known_textbook_ids is None:
            issues.append(
                ContractIssue(
                    "curriculum_mapping.textbook_id",
                    "unknown_textbook_set",
                    "textbook references cannot be verified without a known set",
                )
            )
            curriculum_ok = False
        elif mapping.get("textbook_id") not in known_textbook_ids:
            issues.append(
                ContractIssue(
                    "curriculum_mapping.textbook_id",
                    "unknown_textbook",
                    "curriculum mapping textbook does not exist",
                )
            )
            curriculum_ok = False
        for field_name in ("chapter", "standard_id"):
            if not _non_empty_str(mapping.get(field_name)):
                issues.append(
                    ContractIssue(
                        f"curriculum_mapping.{field_name}",
                        "missing_mapping_field",
                        f"curriculum mapping needs a non-empty {field_name}",
                    )
                )
                curriculum_ok = False
        if not _non_empty_str(mapping.get("reviewed_by")):
            issues.append(
                ContractIssue(
                    "curriculum_mapping.reviewed_by",
                    "missing_human_review",
                    "curriculum mapping needs a named human reviewer",
                )
            )
            curriculum_ok = False
    gates["curriculum"] = "pass" if curriculum_ok else "fail"

    # Formulas and figures.
    gates["formulas"] = _check_formulas(spec, issues)
    gates["figures"] = _check_figures(spec, issues)

    # Atlas recomputation.
    gates["atlas"] = _check_atlas(spec, issues, atlas_check)

    # Knowledge-point label audit.
    label = spec.get("knowledge_label")
    label_ok = True
    if not isinstance(label, Mapping):
        issues.append(
            ContractIssue(
                "knowledge_label",
                "missing_label_review",
                "knowledge-point label needs a human review record",
            )
        )
        label_ok = False
    else:
        if label.get("ku_id") != spec.get("ku_id"):
            issues.append(
                ContractIssue(
                    "knowledge_label.ku_id",
                    "label_mismatch",
                    "reviewed knowledge-point label does not match the question ku_id",
                )
            )
            label_ok = False
        if not _non_empty_str(label.get("reviewed_by")):
            issues.append(
                ContractIssue(
                    "knowledge_label.reviewed_by",
                    "missing_label_reviewer",
                    "knowledge-point label needs a named human reviewer",
                )
            )
            label_ok = False
    gates["labels"] = "pass" if label_ok else "fail"

    failed = [name for name, state in gates.items() if state == "fail"]
    return {"passed": not failed, "gates": gates, "issues": _issues_to_dicts(issues)}


# ── G2: mastery definition ──────────────────────────────────────────────────


def weak_roots_namespace(kind: str) -> Optional[str]:
    """Namespace for one of the two weak_roots meanings, or None."""
    if kind == "cognitive_mastery":
        return "cognitive:weak_roots"
    if kind == "prereq_diagnosis":
        return "prereq:weak_roots"
    return None


def resolve_weak_roots_kind(payload: object) -> dict[str, Any]:
    """Require a weak_roots payload to name which weak_roots it is.

    Returns {"passed", "kind", "namespace", "source", "description",
    "issues"}. An unnamed or unknown kind fails: the two meanings must
    never be mixed silently.
    """
    issues: list[ContractIssue] = []
    if not isinstance(payload, Mapping):
        return {
            "passed": False,
            "kind": None,
            "namespace": None,
            "source": None,
            "description": None,
            "issues": [
                ContractIssue(
                    "weak_roots",
                    "not_an_object",
                    "weak_roots payload must be an object",
                ).to_dict()
            ],
        }
    kind = payload.get("kind")
    if kind not in WEAK_ROOTS_KINDS:
        issues.append(
            ContractIssue(
                "weak_roots.kind",
                "unknown_weak_roots_kind",
                "weak_roots kind must be cognitive_mastery or prereq_diagnosis",
            )
        )
        return {
            "passed": False,
            "kind": kind if isinstance(kind, str) else None,
            "namespace": None,
            "source": None,
            "description": None,
            "issues": _issues_to_dicts(issues),
        }
    source, description = WEAK_ROOTS_KINDS[kind]
    return {
        "passed": True,
        "kind": kind,
        "namespace": weak_roots_namespace(kind),
        "source": source,
        "description": description,
        "issues": [],
    }


def compute_mastery_snapshot(
    *,
    correct: int,
    total: int,
    p_mastery: Optional[float],
    evidence_n: int,
    mastery_confirmed: bool,
    mastery_source: str,
    mastery_method: str,
) -> dict[str, Any]:
    """G2: compute one published mastery snapshot. Mastery != accuracy.

    Accuracy (correct/total) and mastery (BKT/FSRS p_mastery) are
    reported as two separate numbers and never equated: mastery_source
    must be "bkt" or "fsrs"; "direct_accuracy" fails. The computation
    method must be named (mastery_method), so a mastery number that
    happens to equal accuracy cannot pass unexplained, as the audited
    site's did (59.5% mastery = 59.5% accuracy, no formula shown).

    Status bands use the single-source thresholds from learner_model:
    weak below GATE (0.6), developing GATE..MASTERED, estimated_mastered
    at/above MASTERED (0.7) without an isolated gate-check verdict,
    mastered only at/above MASTERED *and* mastery_confirmed. Fewer
    than MIN_EVIDENCE_N attempts of evidence yields
    insufficient_evidence and the snapshot does not pass: no mastery
    label is published from thin evidence.
    """
    issues: list[ContractIssue] = []
    notes: list[str] = []
    if (
        not _is_int(correct)
        or not _is_int(total)
        or correct < 0
        or total < 0
        or correct > total
    ):
        issues.append(
            ContractIssue(
                "attempts",
                "bad_attempt_counts",
                "correct and total must be non-negative integers with correct <= total",
            )
        )
    if not _is_int(evidence_n) or evidence_n < 0:
        issues.append(
            ContractIssue(
                "evidence_n",
                "bad_evidence_n",
                "evidence_n must be a non-negative integer",
            )
        )
    if p_mastery is not None and (
        not isinstance(p_mastery, (int, float)) or not 0.0 <= p_mastery <= 1.0
    ):
        issues.append(
            ContractIssue(
                "p_mastery", "bad_p_mastery", "p_mastery must be a number in [0, 1]"
            )
        )
    if mastery_source not in ("bkt", "fsrs"):
        issues.append(
            ContractIssue(
                "mastery_source",
                "mastery_must_not_be_accuracy",
                "mastery must come from bkt or fsrs inference, never from direct accuracy",
            )
        )
    if not _non_empty_str(mastery_method):
        issues.append(
            ContractIssue(
                "mastery_method",
                "missing_mastery_method",
                "the mastery computation method must be named",
            )
        )
    accuracy = (correct / total) if total > 0 and not issues else None
    if (
        accuracy is not None
        and p_mastery is not None
        and abs(accuracy - p_mastery) < 1e-12
    ):
        notes.append(
            "mastery_p equals accuracy numerically; the named method above "
            "is the only basis for the mastery value, not the accuracy"
        )
    status = "insufficient_evidence"
    if not issues:
        if evidence_n < MIN_EVIDENCE_N or p_mastery is None:
            issues.append(
                ContractIssue(
                    "evidence_n",
                    "insufficient_evidence",
                    f"mastery labels need at least {MIN_EVIDENCE_N} attempts of evidence",
                )
            )
        elif p_mastery < GATE:
            status = "weak"
        elif p_mastery < MASTERED:
            status = "developing"
        elif mastery_confirmed:
            status = "mastered"
        else:
            status = "estimated_mastered"
    return {
        "passed": not issues,
        "status": status,
        "accuracy": accuracy,
        "mastery_p": p_mastery,
        "mastery_source": mastery_source,
        "mastery_method": mastery_method,
        "evidence_n": evidence_n,
        "mastery_confirmed": bool(mastery_confirmed),
        "weak_below": GATE,
        "mastered_at": MASTERED,
        "min_evidence_n": MIN_EVIDENCE_N,
        "notes": notes,
        "issues": _issues_to_dicts(issues),
    }


# ── G3: common-wrong-question aggregation ──────────────────────────────────


def aggregate_common_errors(
    records: object,
    *,
    min_sample: int = MIN_COMMON_ERROR_SAMPLE,
) -> dict[str, Any]:
    """G3 gate: aggregate common wrong questions for publication.

    A record is publishable only when: attempted/wrong/error_rate are
    all present (error_rate is recomputed here and must match any
    supplied value), typical errors are classified from the fixed
    categories, the record carries no identifiable student field, and
    n_attempted >= min_sample (default 5, fail-closed). Records below
    the minimum are withheld in "suppressed" with their reason; they do
    not fail the publishable list, they are simply not shown. Hard
    failures (bad counts, rate mismatch, unclassified errors, student
    identifiers) fail the whole aggregation. Publishable records are
    sorted by error_rate descending, then n_attempted descending.
    """
    issues: list[ContractIssue] = []
    publishable: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    if not isinstance(records, list):
        return {
            "passed": False,
            "publishable": [],
            "suppressed": [],
            "min_sample": min_sample,
            "issues": [
                ContractIssue(
                    "records", "not_a_list", "records must be a list"
                ).to_dict()
            ],
        }
    if not _is_int(min_sample) or min_sample < 1:
        issues.append(
            ContractIssue(
                "min_sample", "bad_min_sample", "min_sample must be a positive integer"
            )
        )
    for pos, record in enumerate(records):
        field = f"records[{pos}]"
        if not isinstance(record, Mapping):
            issues.append(
                ContractIssue(field, "bad_record", "record must be an object")
            )
            continue
        qid = record.get("question_id")
        if not _non_empty_str(qid):
            issues.append(
                ContractIssue(
                    f"{field}.question_id",
                    "missing_question_id",
                    "record needs a question_id",
                )
            )
            continue
        for id_field in IDENTIFIABLE_FIELDS:
            if record.get(id_field) not in (None, "", [], {}):
                issues.append(
                    ContractIssue(
                        f"{field}.{id_field}",
                        "identifiable_student",
                        "aggregated records must not carry identifiable student data",
                    )
                )
        attempted = record.get("n_attempted")
        wrong = record.get("n_wrong")
        record_ok = True
        if (
            not _is_int(attempted)
            or not _is_int(wrong)
            or attempted < 0
            or wrong < 0
            or wrong > attempted
        ):
            issues.append(
                ContractIssue(
                    field,
                    "bad_counts",
                    "n_attempted and n_wrong must be non-negative integers with n_wrong <= n_attempted",
                )
            )
            record_ok = False
        error_rate = (wrong / attempted) if record_ok and attempted > 0 else None
        supplied_rate = record.get("error_rate")
        if supplied_rate is not None:
            if not isinstance(supplied_rate, (int, float)) or error_rate is None:
                issues.append(
                    ContractIssue(
                        f"{field}.error_rate",
                        "bad_error_rate",
                        "error_rate must be a number when n_attempted > 0",
                    )
                )
                record_ok = False
            elif abs(float(supplied_rate) - error_rate) > 1e-9:
                issues.append(
                    ContractIssue(
                        f"{field}.error_rate",
                        "rate_mismatch",
                        "supplied error_rate does not match n_wrong / n_attempted",
                    )
                )
                record_ok = False
        typical = record.get("typical_errors")
        if not isinstance(typical, list) or not typical:
            issues.append(
                ContractIssue(
                    f"{field}.typical_errors",
                    "missing_typical_errors",
                    "record needs at least one classified typical error",
                )
            )
            record_ok = False
        else:
            for epos, error in enumerate(typical):
                efield = f"{field}.typical_errors[{epos}]"
                if not isinstance(error, Mapping):
                    issues.append(
                        ContractIssue(
                            efield,
                            "bad_typical_error",
                            "typical error must be an object",
                        )
                    )
                    record_ok = False
                    continue
                if error.get("category") not in TYPICAL_ERROR_CATEGORIES:
                    issues.append(
                        ContractIssue(
                            f"{efield}.category",
                            "unknown_error_category",
                            "typical error category must be one of "
                            + ", ".join(TYPICAL_ERROR_CATEGORIES),
                        )
                    )
                    record_ok = False
                if not _non_empty_str(error.get("description")):
                    issues.append(
                        ContractIssue(
                            f"{efield}.description",
                            "missing_error_description",
                            "typical error needs a non-empty description",
                        )
                    )
                    record_ok = False
        if not record_ok:
            continue
        if attempted < min_sample:
            suppressed.append(
                {
                    "question_id": qid,
                    "n_attempted": attempted,
                    "n_wrong": wrong,
                    "error_rate": error_rate,
                    "reason": "sample_too_small",
                    "min_sample": min_sample,
                }
            )
            continue
        publishable.append(
            {
                "question_id": qid,
                "n_attempted": attempted,
                "n_wrong": wrong,
                "error_rate": error_rate,
                "typical_errors": [
                    {"category": e["category"], "description": e["description"]}
                    for e in typical
                ],
            }
        )
    publishable.sort(key=lambda r: (-r["error_rate"], -r["n_attempted"]))
    return {
        "passed": not issues,
        "publishable": publishable,
        "suppressed": suppressed,
        "withheld_count": len(suppressed),
        "min_sample": min_sample,
        "issues": _issues_to_dicts(issues),
    }


# ── G4: data-import pipeline ───────────────────────────────────────────────


def dedup_key_for_row(import_type: str, row: Mapping[str, Any]) -> str:
    """Stable dedup key for one import row (the key G4 requires).

    question: normalised stem + answer. paper: name + grade + exam
    time. answer_record: student ref + paper + question_no. student:
    student_no. knowledge_point: kp_id. Two rows with the same key are
    the same row for import purposes.
    """
    if import_type == "question":
        raw = (
            "question|"
            + _norm_text(row.get("stem"))
            + "|"
            + _norm_text(row.get("answer"))
        )
    elif import_type == "paper":
        raw = (
            "paper|"
            + _norm_text(row.get("paper_name"))
            + "|"
            + _norm_text(row.get("grade"))
            + "|"
            + _norm_text(row.get("exam_time"))
        )
    elif import_type == "answer_record":
        student_ref = row.get("student_no") or row.get("student_name") or ""
        raw = (
            "answer|"
            + _norm_text(student_ref)
            + "|"
            + _norm_text(row.get("paper"))
            + "|"
            + _norm_text(row.get("question_no"))
        )
    elif import_type == "student":
        raw = "student|" + _norm_text(row.get("student_no"))
    elif import_type == "knowledge_point":
        raw = "kp|" + _norm_text(row.get("kp_id"))
    else:
        raw = "unknown|" + _norm_text(str(row))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _check_row_kps(
    row: Mapping[str, Any],
    field: str,
    known_ku_ids: Optional[set[str]],
    issues: list[ContractIssue],
) -> bool:
    """Knowledge-point matching for one row. Exact or reviewed-fuzzy only.

    kp_ids must resolve against the known set (unknown set fails
    closed). A fuzzy match is admissible only with a named human
    reviewer (kp_reviewed_by); otherwise it fails. This is the rule
    the audited site never stated: it showed no matching algorithm at
    all, while mislabelling questions widely.
    """
    kp_ids_raw = row.get("kp_ids")
    if not isinstance(kp_ids_raw, str) or not kp_ids_raw.strip():
        issues.append(
            ContractIssue(
                f"{field}.kp_ids", "missing_kp", "row needs at least one kp_id"
            )
        )
        return False
    if known_ku_ids is None:
        issues.append(
            ContractIssue(
                f"{field}.kp_ids",
                "unknown_ku_set",
                "knowledge-point references cannot be verified without a known set",
            )
        )
        return False
    ok = True
    for kp_id in [k.strip() for k in kp_ids_raw.split(",") if k.strip()]:
        if kp_id not in known_ku_ids:
            issues.append(
                ContractIssue(
                    f"{field}.kp_ids",
                    "unknown_kp",
                    f"knowledge-point {kp_id!r} does not exist",
                )
            )
            ok = False
    if row.get("kp_match") == "fuzzy" and not _non_empty_str(row.get("kp_reviewed_by")):
        issues.append(
            ContractIssue(
                f"{field}.kp_match",
                "fuzzy_unreviewed",
                "fuzzy knowledge-point matches need a named human reviewer",
            )
        )
        ok = False
    return ok


def verify_import_batch(
    batch: object,
    *,
    known_ku_ids: Optional[set[str]] = None,
    existing_dedup_keys: Optional[set[str]] = None,
    authorized_pii: bool = False,
    pii_reviewed_by: Optional[str] = None,
) -> dict[str, Any]:
    """G4 gate: validate one import batch before anything is written.

    - import_type must be one of the five; student / answer_record
      import is OFF by default (authorized_pii False fails the batch,
      and an authorised batch still needs a named privacy reviewer).
    - Every row must carry its template fields; difficulty, when
      present, is an integer 1-5; question_type must be a known type,
      and choice questions need their options.
    - Every row gets a dedup key (dedup_key_for_row); duplicates inside
      the batch, or against existing_dedup_keys, fail. An unknown
      existing-key set fails closed: dedup cannot be checked without it.
    - Every row's kp_ids must resolve (G4 matching rule above).
    - Returns {"passed", "rows_checked", "row_errors", "issues"}; a
      batch passes only with zero row errors and zero issues.
    """
    issues: list[ContractIssue] = []
    row_errors: list[dict[str, Any]] = []
    if not isinstance(batch, Mapping):
        return {
            "passed": False,
            "rows_checked": 0,
            "row_errors": [],
            "issues": [
                ContractIssue(
                    "batch", "not_an_object", "batch must be an object"
                ).to_dict()
            ],
        }
    import_type = batch.get("import_type")
    if import_type not in IMPORT_TYPES:
        return {
            "passed": False,
            "rows_checked": 0,
            "row_errors": [],
            "issues": [
                ContractIssue(
                    "import_type",
                    "unknown_import_type",
                    "import_type must be one of " + ", ".join(IMPORT_TYPES),
                ).to_dict()
            ],
        }
    if import_type in PII_IMPORT_TYPES and not authorized_pii:
        issues.append(
            ContractIssue(
                "import_type",
                "pii_import_disabled",
                "student / answer-record import is off by default and needs explicit authorisation",
            )
        )
    elif import_type in PII_IMPORT_TYPES and not _non_empty_str(pii_reviewed_by):
        issues.append(
            ContractIssue(
                "pii_reviewed_by",
                "missing_pii_reviewer",
                "authorised student / answer-record import needs a named privacy reviewer",
            )
        )
    if existing_dedup_keys is None:
        issues.append(
            ContractIssue(
                "existing_dedup_keys",
                "dedup_set_missing",
                "dedup cannot be checked without the existing dedup-key set",
            )
        )
    rows = batch.get("rows")
    if not isinstance(rows, list) or not rows:
        issues.append(
            ContractIssue("rows", "empty_rows", "batch rows must be a non-empty list")
        )
        return {
            "passed": False,
            "rows_checked": 0,
            "row_errors": row_errors,
            "issues": _issues_to_dicts(issues),
        }
    if len(rows) > MAX_IMPORT_ROWS:
        issues.append(
            ContractIssue(
                "rows",
                "too_many_rows",
                f"batch exceeds the {MAX_IMPORT_ROWS}-row bound",
            )
        )
    seen_keys: set[str] = set()
    for pos, row in enumerate(rows):
        field = f"rows[{pos}]"
        errors: list[ContractIssue] = []
        if not isinstance(row, Mapping):
            errors.append(ContractIssue(field, "bad_row", "row must be an object"))
            row_errors.append(
                {
                    "row_index": pos,
                    "dedup_key": None,
                    "errors": _issues_to_dicts(errors),
                }
            )
            continue
        required = TEMPLATE_FIELDS[import_type]
        for name in required:
            if name in ("options_a", "options_b", "options_c", "options_d"):
                continue  # checked below, only for choice questions
            if name == "parent_kp_id":
                continue  # optional: a root knowledge point has no parent
            value = row.get(name)
            # Numeric template fields (difficulty, total_score,
            # question_no) are present when not None; their range is
            # validated separately below.
            present = (
                value is not None
                if name in ("difficulty", "total_score", "question_no")
                else _non_empty_str(value)
            )
            if not present:
                errors.append(
                    ContractIssue(
                        f"{field}.{name}",
                        "missing_field",
                        f"row needs a non-empty {name}",
                    )
                )
        if import_type in ("question", "paper"):
            qtype = row.get("question_type")
            if qtype not in QUESTION_TYPES:
                errors.append(
                    ContractIssue(
                        f"{field}.question_type",
                        "unknown_question_type",
                        "question_type must be one of "
                        + ", ".join(sorted(QUESTION_TYPES)),
                    )
                )
            elif import_type == "question" and qtype in (
                "single_choice",
                "multiple_choice",
            ):
                for name in ("options_a", "options_b", "options_c", "options_d"):
                    if not _non_empty_str(row.get(name)):
                        errors.append(
                            ContractIssue(
                                f"{field}.{name}",
                                "missing_field",
                                f"choice question needs a non-empty {name}",
                            )
                        )
            difficulty = row.get("difficulty")
            if difficulty is not None and (
                not _is_int(difficulty) or not 1 <= difficulty <= 5
            ):
                errors.append(
                    ContractIssue(
                        f"{field}.difficulty",
                        "bad_difficulty",
                        "difficulty must be an integer in 1..5",
                    )
                )
        if import_type == "answer_record":
            if row.get("is_correct") not in (True, False, 0, 1, "true", "false"):
                errors.append(
                    ContractIssue(
                        f"{field}.is_correct",
                        "bad_is_correct",
                        "is_correct must be a boolean value",
                    )
                )
        if import_type in ("question", "paper"):
            if not _check_row_kps(row, field, known_ku_ids, errors):
                pass  # errors appended inside
        dedup_key = dedup_key_for_row(import_type, row)
        if dedup_key in seen_keys:
            errors.append(
                ContractIssue(
                    f"{field}.dedup_key",
                    "duplicate_in_batch",
                    "another row in this batch has the same dedup key",
                )
            )
        elif existing_dedup_keys is not None and dedup_key in existing_dedup_keys:
            errors.append(
                ContractIssue(
                    f"{field}.dedup_key",
                    "duplicate_of_existing",
                    "a row with this dedup key already exists",
                )
            )
        seen_keys.add(dedup_key)
        if errors:
            row_errors.append(
                {
                    "row_index": pos,
                    "dedup_key": dedup_key,
                    "errors": _issues_to_dicts(errors),
                }
            )
    passed = not issues and not row_errors
    return {
        "passed": passed,
        "rows_checked": len(rows),
        "row_errors": row_errors,
        "issues": _issues_to_dicts(issues),
    }
