"""Learner State 2.0 read model.

This module composes existing BKT/FSRS state and observed interaction evidence
into an interpretable, versioned response.  It is intentionally read-only:
mastery changes still enter through SubmitAnswer and the cognitive kernel.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import InteractionEvent, InteractionSource, KCMastery, MasterySnapshot

STATE_VERSION = "learner-state/v2"
MODEL_VERSION = "read-composite/0.1.0"


def _source_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _event_value(event: Any, name: str, default: Any = None) -> Any:
    return getattr(event, name, default)


def _retrievability(card: dict[str, Any] | None, now: datetime) -> float | None:
    if not card:
        return None
    try:
        from oprim.fsrs_engine import fsrs_retrievability

        value = fsrs_retrievability(card_dict=card, now=now)
        return round(max(0.0, min(1.0, float(value))), 6)
    except (TypeError, ValueError, KeyError):
        return None


def _uncertainty(p: float, n: int) -> dict[str, float]:
    """Conservative normal approximation around the observed BKT probability."""

    sigma = math.sqrt(max(0.0, p * (1.0 - p) / (n + 1)))
    return {
        "standard_error": round(sigma, 6),
        "lower_95": round(max(0.0, p - 1.96 * sigma), 6),
        "upper_95": round(min(1.0, p + 1.96 * sigma), 6),
    }


def _metacognition(events: list[Any]) -> dict[str, Any]:
    pairs = []
    for event in events:
        confidence = _event_value(event, "predicted_confidence")
        correctness = _event_value(event, "is_correct")
        if confidence is not None and correctness is not None:
            pairs.append((float(confidence), 1.0 if correctness else 0.0))
    if not pairs:
        return {
            "n": 0,
            "brier": None,
            "overconfidence": None,
            "calibration_status": "insufficient_evidence",
        }
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    overconfidence = sum(p - y for p, y in pairs) / len(pairs)
    status = "well_calibrated" if abs(overconfidence) <= 0.10 else (
        "overconfident" if overconfidence > 0 else "underconfident"
    )
    return {
        "n": len(pairs),
        "brier": round(brier, 6),
        "overconfidence": round(overconfidence, 6),
        "calibration_status": status,
    }


def _transfer(events: list[Any]) -> dict[str, Any]:
    probes = [
        event
        for event in events
        if _source_value(_event_value(event, "source"))
        == InteractionSource.transfer_probe.value
    ]
    if not probes:
        return {"n": 0, "rate": None, "scope": "near_transfer"}
    rate = sum(bool(_event_value(event, "is_correct")) for event in probes) / len(probes)
    return {"n": len(probes), "rate": round(rate, 6), "scope": "near_transfer"}


def _error_profile(events: list[Any]) -> dict[str, Any]:
    incorrect = [event for event in events if not _event_value(event, "is_correct", False)]
    quick = [
        event
        for event in incorrect
        if _event_value(event, "time_spent_seconds") is not None
        and _event_value(event, "time_spent_seconds") < 8
    ]
    low_confidence = [
        event
        for event in incorrect
        if _event_value(event, "predicted_confidence") is not None
        and _event_value(event, "predicted_confidence") < 0.4
    ]
    return {
        "incorrect": len(incorrect),
        "quick_incorrect_proxy": len(quick),
        "low_confidence_incorrect": len(low_confidence),
        "note": "行为代理，不等同于内核 error_type 判定",
    }


def _state_for_mastery(
    mastery: Any,
    events: list[Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    p = float(mastery.p_mastery or 0.0)
    attempts = int(mastery.n_attempts or len(events))
    retrievability = _retrievability(mastery.fsrs_card_json, now)
    effective = p * retrievability if retrievability is not None else p
    transfer = _transfer(events)
    return {
        "knowledge_point": mastery.knowledge_point,
        "mastery": {
            "p_mastery": round(p, 6),
            "long_term_mastery": round(
                float(mastery.long_term_mastery)
                if mastery.long_term_mastery is not None
                else p,
                6,
            ),
            "mastery_confirmed": bool(mastery.mastery_confirmed),
            "effective_mastery": round(effective, 6),
        },
        "memory": {
            "retrievability": retrievability,
            "stability": (
                float(mastery.fsrs_card_json.get("stability"))
                if mastery.fsrs_card_json
                and mastery.fsrs_card_json.get("stability") is not None
                else None
            ),
            "due": (
                mastery.fsrs_card_json.get("due")
                if mastery.fsrs_card_json
                else None
            ),
        },
        "recognition": {
            "p_recognition": (
                round(float(mastery.p_recognition), 6)
                if mastery.p_recognition is not None
                else None
            ),
            "p_recognition_init": (
                round(float(mastery.p_recognition_init), 6)
                if mastery.p_recognition_init is not None
                else None
            ),
        },
        "transfer": transfer,
        "error_profile": _error_profile(events),
        "metacognition": _metacognition(events),
        "uncertainty": _uncertainty(p, attempts),
        "evidence": {
            "attempts": attempts,
            "event_count": len(events),
            "event_ids": [str(_event_value(event, "id")) for event in events],
            "last_interaction_at": (
                mastery.last_interaction_at.isoformat()
                if mastery.last_interaction_at
                else None
            ),
        },
    }


def compose_learner_state(
    masteries: Iterable[Any],
    events: Iterable[Any],
    *,
    student_id: UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure composition function used by the API and deterministic tests."""

    now = now or datetime.now(UTC)
    mastery_rows = list(masteries)
    event_rows = list(events)
    events_by_kc: dict[str, list[Any]] = defaultdict(list)
    for event in event_rows:
        for_kc = _event_value(event, "knowledge_point")
        if for_kc is not None:
            events_by_kc[str(for_kc)].append(event)

    knowledge_points = {
        row.knowledge_point: _state_for_mastery(
            row, events_by_kc.get(row.knowledge_point, []), now=now
        )
        for row in mastery_rows
    }
    mastery_values = [
        value["mastery"]["p_mastery"] for value in knowledge_points.values()
    ]
    memory_values = [
        value["memory"]["retrievability"]
        for value in knowledge_points.values()
        if value["memory"]["retrievability"] is not None
    ]
    transfer_values = [
        value["transfer"]["rate"]
        for value in knowledge_points.values()
        if value["transfer"]["rate"] is not None
    ]
    metacog = [
        value["metacognition"]
        for value in knowledge_points.values()
        if value["metacognition"]["brier"] is not None
    ]
    uncertainty = [
        value["uncertainty"]["standard_error"]
        for value in knowledge_points.values()
    ]
    return {
        "student_id": str(student_id),
        "state_version": STATE_VERSION,
        "model_version": MODEL_VERSION,
        "computed_at": now.isoformat(),
        "summary": {
            "knowledge_points": len(knowledge_points),
            "mean_mastery": (
                round(sum(mastery_values) / len(mastery_values), 6)
                if mastery_values
                else None
            ),
            "mean_retrievability": (
                round(sum(memory_values) / len(memory_values), 6)
                if memory_values
                else None
            ),
            "transfer_rate": (
                round(sum(transfer_values) / len(transfer_values), 6)
                if transfer_values
                else None
            ),
            "metacognition_brier": (
                round(sum(item["brier"] for item in metacog) / len(metacog), 6)
                if metacog
                else None
            ),
            "mean_uncertainty": (
                round(sum(uncertainty) / len(uncertainty), 6)
                if uncertainty
                else None
            ),
            "evidence_event_count": len(event_rows),
        },
        "knowledge_points": knowledge_points,
    }


async def get_learner_state(
    db: AsyncSession,
    student_id: UUID,
    *,
    ku_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    mastery_stmt = select(KCMastery).where(KCMastery.student_id == student_id)
    if ku_id is not None:
        mastery_stmt = mastery_stmt.where(KCMastery.knowledge_point == ku_id)
    masteries = (await db.execute(mastery_stmt)).scalars().all()
    event_stmt = select(InteractionEvent).where(InteractionEvent.student_id == student_id)
    if ku_id is not None:
        event_stmt = event_stmt.where(InteractionEvent.knowledge_point == ku_id)
    event_stmt = event_stmt.order_by(InteractionEvent.occurred_at)
    events = (await db.execute(event_stmt)).scalars().all()
    result = compose_learner_state(masteries, events, student_id=student_id, now=now)
    if ku_id is not None:
        item = result["knowledge_points"].get(ku_id)
        return {
            "student_id": str(student_id),
            "knowledge_point": ku_id,
            "state_version": result["state_version"],
            "model_version": result["model_version"],
            "computed_at": result["computed_at"],
            "started": item is not None,
            "state": item,
        }
    return result


_TERM_RE = re.compile(r"^(?P<year>\d{4})(?:-(?P<part>Q[1-4]|S[12]|\d{2}))?$")


def term_window(term: str) -> tuple[datetime, datetime]:
    """Resolve stable academic reporting terms without depending on local time."""

    match = _TERM_RE.fullmatch(term.upper())
    if not match:
        raise ValueError("term must be YYYY, YYYY-MM, YYYY-Q1..Q4, or YYYY-S1/S2")
    year = int(match.group("year"))
    part = match.group("part")
    if part is None:
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
    elif part.startswith("Q"):
        month = (int(part[1]) - 1) * 3 + 1
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 10 else date(year, month + 3, 1)
    elif part.startswith("S"):
        start = date(year, 1 if part == "S1" else 7, 1)
        end = date(year, 7, 1) if part == "S1" else date(year + 1, 1, 1)
    else:
        month = int(part)
        if not 1 <= month <= 12:
            raise ValueError("month must be in 01..12")
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(end, datetime.min.time(), tzinfo=UTC),
    )


async def growth_summary(
    db: AsyncSession,
    student_id: UUID,
    term: str,
) -> dict[str, Any]:
    start, end = term_window(term)
    events = (
        await db.execute(
            select(InteractionEvent).where(
                InteractionEvent.student_id == student_id,
                InteractionEvent.occurred_at >= start,
                InteractionEvent.occurred_at < end,
            )
        )
    ).scalars().all()
    snapshots = (
        await db.execute(
            select(MasterySnapshot)
            .where(
                MasterySnapshot.student_id == student_id,
                MasterySnapshot.snapshot_month >= start.date(),
                MasterySnapshot.snapshot_month < end.date(),
            )
            .order_by(MasterySnapshot.snapshot_month)
        )
    ).scalars().all()
    by_kc: dict[str, list[float]] = defaultdict(list)
    for row in snapshots:
        if row.long_term_mastery is not None:
            by_kc[str(row.knowledge_point)].append(float(row.long_term_mastery))
    deltas = [values[-1] - values[0] for values in by_kc.values() if len(values) >= 2]
    correct = sum(bool(row.is_correct) for row in events)
    transfer = [
        row for row in events if _source_value(row.source) == InteractionSource.transfer_probe.value
    ]
    active_days = {row.occurred_at.date() for row in events}
    return {
        "student_id": str(student_id),
        "term": term,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "events": len(events),
        "active_days": len(active_days),
        "accuracy": round(correct / len(events), 6) if events else None,
        "transfer_rate": (
            round(sum(bool(row.is_correct) for row in transfer) / len(transfer), 6)
            if transfer
            else None
        ),
        "transfer_n": len(transfer),
        "mastery_growth": {
            "knowledge_points_with_two_snapshots": len(deltas),
            "mean_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
        },
        "snapshot_count": len(snapshots),
    }
