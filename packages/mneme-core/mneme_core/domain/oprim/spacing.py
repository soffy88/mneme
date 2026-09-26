"""Compatibility adapter for the canonical FSRS engine.

Queue construction remains a pure value-object operation, but card scheduling
delegates to ``oprim.fsrs_engine``. The former simplified formulas are gone so
this package has no independent spacing algorithm authority.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fsrs import Rating
from mneme_core.domain.oprim.models import FsrsState, ReviewTask
from oprim.fsrs_engine import fsrs_new_card, fsrs_review


def _iso(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _seconds(value: object, fallback: float) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    return fallback


def get_initial_state(now: float) -> FsrsState:
    card = fsrs_new_card()
    return FsrsState(
        stability=float(card.get("stability") or 1.0),
        difficulty=float(card.get("difficulty") or 5.0),
        last_review=now,
        due_at=_seconds(card.get("due"), now),
        reps=int(card.get("reps") or 0),
    )


def schedule_next(state: FsrsState, rating: int, now: float) -> FsrsState:
    rating_enum = {
        1: Rating.Again,
        2: Rating.Hard,
        3: Rating.Good,
        4: Rating.Easy,
    }[max(1, min(4, rating))]
    card = fsrs_new_card()
    card["stability"] = state.stability
    card["difficulty"] = state.difficulty
    card["reps"] = state.reps
    card["last_review"] = _iso(state.last_review).isoformat()
    card["due"] = _iso(state.due_at).isoformat()
    updated = fsrs_review(card_dict=card, rating=rating_enum, now=_iso(now))
    return FsrsState(
        stability=float(updated.get("stability") or state.stability),
        difficulty=float(updated.get("difficulty") or state.difficulty),
        last_review=now,
        due_at=_seconds(updated.get("due"), now),
        reps=int(updated.get("reps") or state.reps + 1),
    )


def build_review_queue(
    fsrs: dict[str, FsrsState], error_linked: set[str]
) -> list[ReviewTask]:
    tasks = [
        ReviewTask(
            knowledge_point_id=kp_id,
            due_at=state.due_at,
            priority=1 if kp_id in error_linked else 2,
        )
        for kp_id, state in fsrs.items()
    ]
    tasks.sort(key=lambda task: (task.priority, task.due_at))
    return tasks


def due_reviews(queue: list[ReviewTask], now: float) -> list[ReviewTask]:
    due = [task for task in queue if task.due_at <= now]
    due.sort(key=lambda task: (task.priority, task.due_at))
    return due
