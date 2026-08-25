"""Runtime Echo-Loop composition built on the vendored oprim primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict

from oprim import KCState
from oprim.bkt import bkt_update, classify_error, error_weights
from oprim.echo_loop import (
    BlindListenOutput,
    IntensiveListenOutput,
    RetellOutput,
    ShadowingOutput,
    blind_listen_generate,
    intensive_listen_parse,
    retell_evaluate,
    shadowing_evaluate,
)
from oprim.fsrs_engine import fsrs_map_rating, fsrs_retrievability, fsrs_review


class EchoLoopStage(BaseModel):
    value: str
    completed: bool = False
    mastery_updates: int = 0


class EchoLoopResult(BaseModel):
    stage: EchoLoopStage
    blind_listen: Optional[BlindListenOutput] = None
    intensive_listen: Optional[IntensiveListenOutput] = None
    shadowing: Optional[ShadowingOutput] = None
    retell: Optional[RetellOutput] = None
    kc_state: KCState
    card_dict: dict
    effective_mastery: float
    session_id: str
    timestamps: dict
    model_config = ConfigDict(arbitrary_types_allowed=True)


class CognitiveUpdateInput(BaseModel):
    state: KCState
    card_dict: dict
    overall_result: dict
    step_evidence: Optional[str] = None
    now: datetime | None = None
    min_review_interval_hours: float = 0.0
    model_config = ConfigDict(arbitrary_types_allowed=True)


def _update_cognitive_state(*, input: CognitiveUpdateInput) -> dict:
    now = input.now or datetime.now(timezone.utc)
    overall = input.overall_result
    retell = overall.get("retell") or {}
    is_correct = retell.get("overall_score", 0.0) >= 0.6
    retrievability = fsrs_retrievability(card_dict=input.card_dict, now=now)
    bkt_update(
        state=input.state,
        is_correct=is_correct,
        retrievability=retrievability,
        difficulty=retell.get("coverage_score", 0.5),
    )
    error_type = None
    if not is_correct:
        error_type = classify_error(state=input.state, difficulty=0.5)
        careless, dont_know = error_weights(state=input.state, difficulty=0.5)
        if (
            input.step_evidence in ("careless", "dontknow")
            and input.step_evidence != error_type
            and max(careless, dont_know) > 0
            and min(careless, dont_know) / max(careless, dont_know) >= 0.8
        ):
            error_type = input.step_evidence
    rating = fsrs_map_rating(
        is_correct=is_correct,
        struggled=bool(retell.get("hallucinated_points")),
        effortless=retell.get("fluency_score", 1.0) >= 0.8,
    )
    new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now)
    mastery = (input.state.long_term_mastery or input.state.current()) * retrievability
    return {
        "kc_state": input.state,
        "card_dict": new_card,
        "error_type": error_type,
        "rating": rating.name,
        "rating_val": rating.value,
        "effective_mastery": round(mastery, 4),
        "schedule_advanced": True,
    }


async def run_complete_echo_loop(
    *,
    audio_b64: str,
    transcript: str,
    student_retell: str,
    reference_kc_ids: list[str],
    kc_state: KCState,
    card_dict: dict,
    student_audio_b64: Optional[str] = None,
    now: Optional[datetime] = None,
) -> EchoLoopResult:
    current_time = now or datetime.now(timezone.utc)
    blind = await blind_listen_generate(
        audio_b64=audio_b64,
        transcript=transcript,
        reference_kc_ids=reference_kc_ids,
    )
    intensive = await intensive_listen_parse(
        transcript=transcript,
        blind_listen_output=blind.model_dump(),
    )
    shadowing = (
        await shadowing_evaluate(
            reference_text=transcript,
            student_audio_b64=student_audio_b64,
        )
        if student_audio_b64
        else None
    )
    retell = await retell_evaluate(
        original_text=transcript,
        student_retell=student_retell or "",
        reference_kc_ids=reference_kc_ids,
    )
    cognitive = _update_cognitive_state(
        input=CognitiveUpdateInput(
            state=kc_state,
            card_dict=card_dict,
            overall_result={"retell": retell.model_dump()},
            now=current_time,
        )
    )
    return EchoLoopResult(
        stage=EchoLoopStage(value="completed", completed=True, mastery_updates=1),
        blind_listen=blind,
        intensive_listen=intensive,
        shadowing=shadowing,
        retell=retell,
        kc_state=cognitive["kc_state"],
        card_dict=cognitive["card_dict"],
        effective_mastery=cognitive["effective_mastery"],
        session_id=f"echo_loop_{current_time.timestamp()}",
        timestamps={"blind_listen": 0, "intensive_listen": 0, "shadowing": 0, "retell": 0},
    )
