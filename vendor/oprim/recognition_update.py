"""Recognition-based learning state update (BKT with recognition signal).

Pure algorithm, no LLM.  Updates mastery probability based on whether
the student recognised the answer before seeing it.

Version: oprim v3.3.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RecognitionState:
    """Knowledge component state with recognition signal."""

    kc_id: str
    p_mastery: float = 0.20
    p_transit: float = 0.20
    p_guess: float = 0.15
    p_slip: float = 0.12
    p_recognise_given_mastered: float = 0.95
    p_recognise_given_not_mastered: float = 0.30
    n_attempts: int = 0
    last_correct: Optional[bool] = None


@dataclass(frozen=True)
class RecognitionUpdateResult:
    """Result of a recognition-based update step."""

    kc_id: str
    p_mastery_before: float
    p_mastery_after: float
    delta_p: float
    recognised: bool
    was_correct: bool
    updated: bool = True


def recognition_update(
    state: RecognitionState,
    correct: bool,
    recognised: bool,
    *,
    p_transit: float | None = None,
    p_guess: float | None = None,
    p_slip: float | None = None,
) -> RecognitionUpdateResult:
    """Update mastery probability incorporating recognition signal.

    BKT update with an additional recognition layer:
    - If the student recognised the answer → boost mastery estimate.
    - If not recognised but correct → standard BKT update.

    Parameters
    ----------
    state : RecognitionState
        Current KC state.
    correct : bool
        Whether the student answered correctly.
    recognised : bool
        Whether the student recognised the answer before seeing it.
    p_transit, p_guess, p_slip : float | None
        Override state-level parameters for this update.

    Returns
    -------
    RecognitionUpdateResult
        Before/after mastery probabilities.
    """
    pt = p_transit if p_transit is not None else state.p_transit
    pg = p_guess if p_guess is not None else state.p_guess
    ps = p_slip if p_slip is not None else state.p_slip

    p = state.p_mastery
    p_before = p

    # Standard BKT update
    if correct:
        p_correct_given_mastered = 1.0 - ps
        p_correct_given_not = pg
    else:
        p_correct_given_mastered = ps
        p_correct_given_not = 1.0 - pg

    p_correct_total = p * p_correct_given_mastered + (1.0 - p) * p_correct_given_not

    if p_correct_total > 0:
        if correct:
            p = (p * p_correct_given_mastered) / p_correct_total
        else:
            p = (p * ps) / (p * ps + (1.0 - p) * (1.0 - pg)) if (p * ps + (1.0 - p) * (1.0 - pg)) > 0 else p
    # else: p stays the same (no information)

    # Recognition boost: if recognised, push mastery higher
    if recognised and not correct:
        # Recognised but wrong → unusual, apply small negative adjustment
        p_r_given_m = state.p_recognise_given_mastered
        p_r_given_nm = state.p_recognise_given_not_mastered
        p_rec_total = p * p_r_given_m + (1.0 - p) * p_r_given_nm
        if p_rec_total > 0:
            p = (p * p_r_given_m) / p_rec_total
    elif recognised and correct:
        # Both correct and recognised → strong evidence of mastery
        p_r_given_m = state.p_recognise_given_mastered
        p_r_given_nm = state.p_recognise_given_not_mastered
        p_rec_total = p * p_r_given_m + (1.0 - p) * p_r_given_nm
        if p_rec_total > 0:
            p = (p * p_r_given_m) / p_rec_total

    # Transition
    p = p + (1.0 - p) * pt

    # Clamp
    p = max(0.001, min(0.999, p))

    delta = p - p_before

    return RecognitionUpdateResult(
        kc_id=state.kc_id,
        p_mastery_before=round(p_before, 6),
        p_mastery_after=round(p, 6),
        delta_p=round(delta, 6),
        recognised=recognised,
        was_correct=correct,
        updated=True,
    )


def recognition_update_sequence(
    state: RecognitionState,
    interactions: list[tuple[bool, bool]],
) -> list[RecognitionUpdateResult]:
    """Apply a sequence of (correct, recognised) interactions.

    Parameters
    ----------
    state : RecognitionState
        Initial state (modified in place for mastery).
    interactions : list[tuple[bool, bool]]
        List of (correct, recognised) tuples in chronological order.

    Returns
    -------
    list[RecognitionUpdateResult]
        One result per interaction.
    """
    results: list[RecognitionUpdateResult] = []
    current = RecognitionState(
        kc_id=state.kc_id,
        p_mastery=state.p_mastery,
        p_transit=state.p_transit,
        p_guess=state.p_guess,
        p_slip=state.p_slip,
        p_recognise_given_mastered=state.p_recognise_given_mastered,
        p_recognise_given_not_mastered=state.p_recognise_given_not_mastered,
        n_attempts=state.n_attempts,
    )

    for correct, recognised in interactions:
        result = recognition_update(current, correct, recognised)
        current.p_mastery = result.p_mastery_after
        current.n_attempts += 1
        current.last_correct = correct
        results.append(result)

    return results
