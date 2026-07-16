"""mneme-core spacing — FSRS state update and review queue management.

Pure functions, no IO.  Time is always passed as ``now: float`` (unix ts).
Uses simplified FSRS formulas for stability/difficulty updates.
"""
from __future__ import annotations

from mneme_core.oprim.models import FsrsState, ReviewTask

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_INITIAL_STABILITY = 1.0  # days
_INITIAL_DIFFICULTY = 5.0  # 1–10 scale
_DAY_SECONDS = 86_400.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_initial_state(now: float) -> FsrsState:
    """Return a fresh FSRS state with default stability & difficulty.

    The first review is due immediately (``due_at == now``).
    """
    return FsrsState(
        stability=_INITIAL_STABILITY,
        difficulty=_INITIAL_DIFFICULTY,
        last_review=now,
        due_at=now,
        reps=0,
    )


def schedule_next(state: FsrsState, rating: int, now: float) -> FsrsState:
    """Compute the next FSRS state after a review with the given *rating*.

    Args:
        state: Current FSRS state (not mutated).
        rating: Quality rating 1–4 (1=again, 2=hard, 3=good, 4=easy).
        now: Current unix timestamp.

    Returns:
        A NEW ``FsrsState`` with updated stability, difficulty, due_at, etc.

    Simplified FSRS formulas:
        - difficulty is adjusted ±0.5 based on rating vs. 3 (neutral),
          clamped to [1, 10].
        - stability is multiplied by a factor derived from the rating,
          with a floor of 0.1 days.
        - interval = stability days → due_at = now + interval.
    """
    rating = max(1, min(4, rating))

    # --- Difficulty update ---
    delta_d = (3 - rating) * 0.5  # positive when rating < 3 (harder)
    new_difficulty = max(1.0, min(10.0, state.difficulty + delta_d))

    # --- Stability update ---
    # Rating multipliers: again=0.2, hard=0.8, good=2.5, easy=4.0
    multipliers = {1: 0.2, 2: 0.8, 3: 2.5, 4: 4.0}
    new_stability = max(0.1, state.stability * multipliers[rating])

    # --- Interval → due_at ---
    interval_secs = new_stability * _DAY_SECONDS
    new_due_at = now + interval_secs

    return FsrsState(
        stability=new_stability,
        difficulty=new_difficulty,
        last_review=now,
        due_at=new_due_at,
        reps=state.reps + 1,
    )


def build_review_queue(
    fsrs: dict[str, FsrsState],
    error_linked: set[str],
) -> list[ReviewTask]:
    """Build a full review queue from FSRS states.

    Error-linked KPs get ``priority=1`` (highest).  All others get
    ``priority=2`` and are sorted by ``due_at`` ascending.

    Args:
        fsrs: Mapping of knowledge-point ID → current FSRS state.
        error_linked: Set of KP IDs that are linked to recent errors.

    Returns:
        A NEW sorted list of ``ReviewTask`` objects.
    """
    tasks: list[ReviewTask] = []
    for kp_id, state in fsrs.items():
        priority = 1 if kp_id in error_linked else 2
        tasks.append(
            ReviewTask(
                knowledge_point_id=kp_id,
                due_at=state.due_at,
                priority=priority,
            )
        )
    # Sort by priority ascending (1 first), then by due_at ascending.
    tasks.sort(key=lambda t: (t.priority, t.due_at))
    return tasks


def due_reviews(queue: list[ReviewTask], now: float) -> list[ReviewTask]:
    """Filter and sort reviews that are due (``due_at <= now``).

    Returns a NEW list sorted by priority ascending (error-linked first),
    then by ``due_at`` ascending within the same priority.
    """
    due = [t for t in queue if t.due_at <= now]
    due.sort(key=lambda t: (t.priority, t.due_at))
    return due
