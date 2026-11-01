"""Dictation practice loop (Parroto method, clean rewrite, own corpus).

Listen, type verbatim, get a deterministic word-level diff. Scoring
rules are written down, never fuzzy: case-insensitive,
punctuation-insensitive, contractions stay whole tokens. Missed words
become review items through the existing FSRS discipline only; nothing
here writes mastery. Audio is never synthesized here: the spec carries
source text and the TTS text is the text itself.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

MAX_SEGMENTS = 12
MAX_SEGMENT_CHARS = 600


def tokenize(text: str) -> list[str]:
    """Lowercase, drop punctuation, keep contractions whole."""
    return _TOKEN_RE.findall(text.lower())


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def diff_words(reference_tokens: list[str], typed_tokens: list[str]) -> list[dict[str, Any]]:
    """Word-level alignment. Statuses: correct / missing / wrong / extra."""
    matcher = difflib.SequenceMatcher(a=reference_tokens, b=typed_tokens, autojunk=False)
    results: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for pos in range(i1, i2):
                results.append({"word": reference_tokens[pos], "status": "correct", "ref_index": pos, "typed_index": j1 + (pos - i1)})
        elif tag == "delete":
            for pos in range(i1, i2):
                results.append({"word": reference_tokens[pos], "status": "missing", "ref_index": pos, "typed_index": None})
        elif tag == "insert":
            for pos in range(j1, j2):
                results.append({"word": typed_tokens[pos], "status": "extra", "ref_index": None, "typed_index": pos})
        elif tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
            for offset in range(pairs):
                results.append({"word": reference_tokens[i1 + offset], "status": "wrong", "ref_index": i1 + offset, "typed_index": j1 + offset, "typed_word": typed_tokens[j1 + offset]})
            for pos in range(i1 + pairs, i2):
                results.append({"word": reference_tokens[pos], "status": "missing", "ref_index": pos, "typed_index": None})
            for pos in range(j1 + pairs, j2):
                results.append({"word": typed_tokens[pos], "status": "extra", "ref_index": None, "typed_index": pos})
    return results


class DictationIssue:
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


def verify_dictation_spec(
    spec: Mapping[str, Any], passage_text: Optional[str] = None
) -> tuple[dict[str, bool], list[DictationIssue]]:
    """Six gates; passage consistency is fail-closed when text is supplied."""
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 7)}
    issues: list[DictationIssue] = []

    def fail(gate: str, issue: DictationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        return gates, [DictationIssue("", "not_an_object", "spec must be an object")]
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id or len(spec_id) > 100:
        fail("g1", DictationIssue("id", "bad_id", "id must be a non-empty string of at most 100 chars"))
    segments = spec.get("segments")
    if not isinstance(segments, list) or not segments:
        fail("g1", DictationIssue("segments", "missing_segments", "segments must be a non-empty list"))
        segments = []
    if len(segments) > MAX_SEGMENTS:
        fail("g1", DictationIssue("segments", "too_many_segments", "too many segments"))
    if not _is_bilingual(spec.get("title")):
        fail("g2", DictationIssue("title", "bad_title", "title must carry non-empty zh and en"))
    if spec.get("language") not in ("zh", "en"):
        fail("g2", DictationIssue("language", "bad_language", "language must be zh or en"))
    level = spec.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
        fail("g2", DictationIssue("level", "bad_level", "level must be an integer from 1 to 5"))
    for pos, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("index") != pos:
            fail("g3", DictationIssue(f"segments[{pos}]", "bad_segment_index", "segment indices must be contiguous from 0"))
            continue
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            fail("g3", DictationIssue(f"segments[{pos}].text", "empty_segment", "segment text must be non-empty"))
        elif len(text) > MAX_SEGMENT_CHARS:
            fail("g3", DictationIssue(f"segments[{pos}].text", "segment_too_long", "segment text too long"))
    source = spec.get("source")
    if not isinstance(source, dict) or source.get("kind") not in ("self_written", "graded_passage"):
        fail("g4", DictationIssue("source", "bad_source", "source kind must be self_written or graded_passage"))
    elif source.get("kind") == "graded_passage":
        if not isinstance(source.get("passage_id"), str) or not source["passage_id"]:
            fail("g4", DictationIssue("source.passage_id", "missing_passage_id", "graded_passage source needs a passage_id"))
        elif passage_text is not None:
            joined = " ".join(str(s.get("text", "")) for s in segments if isinstance(s, dict))
            if _normalize_space(joined) != _normalize_space(passage_text):
                fail("g4", DictationIssue("segments", "passage_mismatch", "segment texts must join to the passage text"))
    if passage_text is None and isinstance(source, dict) and source.get("kind") == "graded_passage":
        fail("g4", DictationIssue("source", "unknown_passage", "passage text is required to verify a graded_passage source"))
    if "verified" in spec:
        fail("g5", DictationIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))
    full_tokens = tokenize(" ".join(str(s.get("text", "")) for s in segments if isinstance(s, dict)))
    if not full_tokens:
        fail("g6", DictationIssue("segments", "no_tokens", "spec text must contain at least one word"))
    return gates, issues


def grade_dictation(reference_segments: list[Mapping[str, Any]], typed_text: str) -> dict[str, Any]:
    """Grade typed text against reference segments. Pure and deterministic."""
    ref_tokens: list[str] = []
    boundaries: list[tuple[int, int]] = []
    for segment in reference_segments:
        tokens = tokenize(str(segment.get("text", "")))
        boundaries.append((len(ref_tokens), len(ref_tokens) + len(tokens)))
        ref_tokens.extend(tokens)
    typed_tokens = tokenize(typed_text or "")
    word_results = diff_words(ref_tokens, typed_tokens)
    per_segment: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(boundaries):
        segment_words = [r for r in word_results if r.get("ref_index") is not None and start <= r["ref_index"] < end]
        correct = sum(1 for r in segment_words if r["status"] == "correct")
        total = end - start
        per_segment.append(
            {
                "index": idx,
                "correct": correct,
                "total": total,
                "score": (correct / total) if total else 0.0,
                "missed_words": [r["word"] for r in segment_words if r["status"] in ("missing", "wrong")],
            }
        )
    total_correct = sum(1 for r in word_results if r["status"] == "correct")
    return {
        "words": word_results,
        "segments": per_segment,
        "correct": total_correct,
        "total": len(ref_tokens),
        "score": (total_correct / len(ref_tokens)) if ref_tokens else 0.0,
        "missed_words": sorted({r["word"] for r in word_results if r["status"] in ("missing", "wrong")}),
    }


def compute_dictation_schedule(
    *,
    all_correct: bool,
    previous_card: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> tuple[dict, datetime]:
    """FSRS scheduling via the existing discipline, on a detached card.

    schedule_after_answer mutates a WrongQuestion; here it runs against
    a never-persisted instance so dictation attempts get FSRS dues
    without polluting wrong_questions and without touching mastery.
    """
    from services.models import WrongQuestion
    from services.wrongbook_review_service import schedule_after_answer

    now = now or datetime.now(timezone.utc)
    probe = WrongQuestion()
    probe.fsrs_card_json = previous_card
    probe.review_count = 0
    probe.review_correct_streak = 0
    outcome = schedule_after_answer(probe, is_correct=all_correct, struggled=not all_correct, now=now)
    due = outcome["next_due"]
    if isinstance(due, str):
        due = datetime.fromisoformat(due.replace("Z", "+00:00"))
    return dict(probe.fsrs_card_json or {}), due


def self_written_passages() -> list[dict[str, Any]]:
    """First corpus: three original English passages, levels 1-3.

    Written for this graft. No third-party content is used anywhere
    in the dictation loop.
    """
    return [
        {
            "id": "dict-l1-morning",
            "title": {"zh": "早晨", "en": "Morning"},
            "language": "en",
            "level": 1,
            "source": {"kind": "self_written"},
            "segments": [
                {"index": 0, "text": "Hello, my name is Lin. I am ten years old."},
                {"index": 1, "text": "I have a dog. His name is Bai."},
                {"index": 2, "text": "Every morning, we run in the park. The park is near my home."},
            ],
        },
        {
            "id": "dict-l2-market",
            "title": {"zh": "市场", "en": "At the Market"},
            "language": "en",
            "level": 2,
            "source": {"kind": "self_written"},
            "segments": [
                {"index": 0, "text": "Last Saturday, Mei and her brother went to the market."},
                {"index": 1, "text": "They bought apples, bread, and milk."},
                {"index": 2, "text": "On the way home, it started to rain, so they waited under a big tree."},
                {"index": 3, "text": "After ten minutes, the rain stopped, and a rainbow appeared in the sky."},
            ],
        },
        {
            "id": "dict-l3-listening",
            "title": {"zh": "先听后说", "en": "Listen First"},
            "language": "en",
            "level": 3,
            "source": {"kind": "self_written"},
            "segments": [
                {"index": 0, "text": "When people learn a new language, listening comes first."},
                {"index": 1, "text": "A child hears thousands of words before she speaks her first sentence."},
                {"index": 2, "text": "Dictation trains the ear to catch every sound, and shadowing trains the mouth to follow the rhythm."},
                {"index": 3, "text": "Fifteen minutes a day is enough if you never miss a day."},
            ],
        },
    ]


__all__ = [
    "DictationIssue",
    "compute_dictation_schedule",
    "diff_words",
    "grade_dictation",
    "self_written_passages",
    "tokenize",
    "verify_dictation_spec",
]
