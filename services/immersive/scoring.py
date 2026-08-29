"""Deterministic practice scorers for Immersive Learning MVP."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.casefold().strip()
    value = value.replace("\u2019", "'").replace("`", "'")
    value = _PUNCT.sub(" ", value)
    value = _SPACE.sub(" ", value).strip()
    return value


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


@dataclass(frozen=True, slots=True)
class ScoreResult:
    correctness: bool
    partial_credit: float
    edit_distance: int
    normalized_expected: str
    normalized_submitted: str
    verifier: str
    verifier_version: str


def score_dictation(expected: str, submitted: str) -> ScoreResult:
    exp = normalize_answer(expected)
    sub = normalize_answer(submitted)
    distance = levenshtein(exp, sub)
    denom = max(len(exp), 1)
    ratio = 1.0 - (distance / denom)
    partial = max(0.0, min(1.0, round(ratio, 4)))
    correct = distance == 0 or partial >= 0.92
    return ScoreResult(
        correctness=correct,
        partial_credit=1.0 if correct and distance == 0 else partial,
        edit_distance=distance,
        normalized_expected=exp,
        normalized_submitted=sub,
        verifier="immersive.dictation_normalize",
        verifier_version="dictation-score/1.0.0",
    )


def score_comprehension_choice(
    expected_option_id: str, submitted_option_id: str
) -> ScoreResult:
    exp = (expected_option_id or "").strip()
    sub = (submitted_option_id or "").strip()
    correct = exp != "" and exp == sub
    return ScoreResult(
        correctness=correct,
        partial_credit=1.0 if correct else 0.0,
        edit_distance=0 if correct else 1,
        normalized_expected=exp,
        normalized_submitted=sub,
        verifier="immersive.comprehension_choice",
        verifier_version="comprehension-score/1.0.0",
    )


def score_listening_meaning(expected: str, submitted: str) -> ScoreResult:
    """Meaning check via normalized token overlap (deterministic baseline)."""

    exp_tokens = set(normalize_answer(expected).split())
    sub_tokens = set(normalize_answer(submitted).split())
    if not exp_tokens:
        return ScoreResult(
            correctness=False,
            partial_credit=0.0,
            edit_distance=1,
            normalized_expected="",
            normalized_submitted=normalize_answer(submitted),
            verifier="immersive.listening_overlap",
            verifier_version="listening-score/1.0.0",
        )
    overlap = len(exp_tokens & sub_tokens) / len(exp_tokens)
    partial = round(overlap, 4)
    correct = partial >= 0.7
    return ScoreResult(
        correctness=correct,
        partial_credit=partial,
        edit_distance=0 if correct else 1,
        normalized_expected=" ".join(sorted(exp_tokens)),
        normalized_submitted=" ".join(sorted(sub_tokens)),
        verifier="immersive.listening_overlap",
        verifier_version="listening-score/1.0.0",
    )
