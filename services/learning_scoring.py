"""Answer scoring + FSRS rating policy for the learning product.

Pure logic (no DB) — fully unit-testable. The LearningEngine routes FSRS
updates through cognitive_service.process_interaction (the single FSRS
authority); this module only derives ratings and scores answers.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TaskType(str, Enum):
    EN_TO_ZH = "EN_TO_ZH"
    ZH_TO_EN = "ZH_TO_EN"
    SPELLING = "SPELLING"
    LISTENING_RECOGNITION = "LISTENING_RECOGNITION"
    CONTEXT_CLOZE = "CONTEXT_CLOZE"


class Score(str, Enum):
    CORRECT = "CORRECT"
    PARTIAL = "PARTIAL"
    INCORRECT = "INCORRECT"
    SKIPPED = "SKIPPED"


class FSRSRating(str, Enum):
    AGAIN = "Again"
    HARD = "Hard"
    GOOD = "Good"
    EASY = "Easy"


@dataclass
class ScoreResult:
    score: Score
    detail: str = ""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def score_en_to_zh(expected_zh: str, answer: str, aliases: Optional[list[str]] = None) -> ScoreResult:
    """EN→ZH: tolerant of synonymous expressions (normalized match)."""
    ans = _normalize(answer)
    candidates = [_normalize(expected_zh)] + [_normalize(a) for a in (aliases or [])]
    if ans in candidates:
        return ScoreResult(Score.CORRECT)
    for c in candidates:
        if ans and (ans in c or c in ans) and len(ans) >= 2:
            return ScoreResult(Score.PARTIAL, "synonym")
    return ScoreResult(Score.INCORRECT)


def score_zh_to_en(expected_en: str, answer: str) -> ScoreResult:
    """ZH→EN: strict but tolerant of case/whitespace/apostrophe."""
    ans = _normalize(answer).replace("'", "'").replace("'", "'")
    exp = _normalize(expected_en).replace("'", "'").replace("'", "'")
    if ans == exp:
        return ScoreResult(Score.CORRECT)
    if ans.replace(" ", "") == exp.replace(" ", ""):
        return ScoreResult(Score.PARTIAL, "whitespace")
    return ScoreResult(Score.INCORRECT)


def score_spelling(expected: str, answer: str) -> ScoreResult:
    """Spelling: exact after normalization; edit distance for diagnostics."""
    ans = _normalize(answer)
    exp = _normalize(expected)
    if ans == exp:
        return ScoreResult(Score.CORRECT)
    dist = _levenshtein(ans, exp)
    if dist == 1 and len(exp) >= 4:
        return ScoreResult(Score.PARTIAL, f"edit_distance={dist}")
    return ScoreResult(Score.INCORRECT, f"edit_distance={dist}")


def score_listening(expected: str, answer: str) -> ScoreResult:
    """Listening recognition: multiple-choice style — exact match on choice."""
    return score_zh_to_en(expected, answer)


def score_cloze(expected: str, answer: str, sentence: str = "") -> ScoreResult:
    """Context cloze: fill-in-the-blank from a real sentence."""
    return score_zh_to_en(expected, answer)


def derive_fsrs_rating(
    score: Score,
    *,
    used_hint: bool = False,
    latency_ms: Optional[int] = None,
    fast_threshold_ms: int = 3000,
) -> FSRSRating:
    """Map a Score to an FSRS rating via domain policy (SPEC §86)."""
    if score == Score.INCORRECT:
        return FSRSRating.AGAIN
    if score == Score.SKIPPED:
        return FSRSRating.AGAIN
    if score == Score.PARTIAL or used_hint:
        return FSRSRating.HARD
    if latency_ms is not None and latency_ms <= fast_threshold_ms:
        return FSRSRating.EASY
    return FSRSRating.GOOD
