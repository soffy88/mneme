"""Deterministic Tutor control and answer-leakage contract.

The Tutor is a five-part control loop, not an unconstrained chat completion:

    observe -> decide -> generate -> verify -> record

This module only makes the first two decisions and supplies the final-output
guard.  It never grades an answer, writes mastery, or treats an LLM statement
as evidence.  Services may add the resulting decision to a Learning Event;
the SubmitAnswer path remains the only mastery write path.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

CONTROL_VERSION = "tutor-control/v1"

# Contexts are intentionally strings: they are part of the HTTP/event contract
# and must remain forward-compatible with clients that only know the fallback.
OWN_HOMEWORK = "own_homework"
WRITING = "writing"
SYSTEM_TAUGHT = "system_taught"
STUCK = "stuck"

NEVER = "never"
FULL_EXAMPLE = "full_example"
HINT_LADDER = "hint_ladder"

OBSERVE = "observe"
DECIDE = "decide"
GENERATE = "generate"
VERIFY = "verify"
RECORD = "record"
CONTROL_PHASES = (OBSERVE, DECIDE, GENERATE, VERIFY, RECORD)

ASK = "ask"
HINT = "hint"
CONTRAST = "contrast"
WORKED_EXAMPLE = "worked_example"
RETRIEVAL = "retrieval"
REFLECT = "reflect"
PEDAGOGICAL_MOVES = (ASK, HINT, CONTRAST, WORKED_EXAMPLE, RETRIEVAL, REFLECT)

_ANSWER_MARKER = re.compile(
    r"(?:答案|正确答案|最终答案|the\s+answer|final\s+answer)"
    r"\s*(?:是|为|is|:|：)?",
    re.IGNORECASE,
)


def answer_policy(
    context: str,
    stage: str | None = None,
    *,
    enabled: bool = False,
) -> dict[str, object]:
    """Return the conservative, deterministic answer-tier policy.

    ``stage`` is the learner-model stage (worked_example/completion/retrieval/
    consolidation), not a mastery decision made by the Tutor.  Hard redlines
    are checked before the feature flag so a caller cannot bypass them.
    """

    def make(mode: str, rationale: str) -> dict[str, object]:
        return {
            "mode": mode,
            "allow_full_answer": mode == FULL_EXAMPLE,
            "allow_worked_example": mode == FULL_EXAMPLE,
            "rationale": rationale,
        }

    if context == OWN_HOMEWORK:
        return make(NEVER, "学生自带原题：不给可抄答案")
    if context == WRITING:
        return make(NEVER, "写作：不代写成段，只提供标注、提问和 rubric")
    if not enabled:
        return make(NEVER, "教学引擎未开启，保守回退")
    if context == SYSTEM_TAUGHT:
        if stage == "worked_example":
            return make(FULL_EXAMPLE, "系统同构新知：允许结构化 worked example")
        return make(HINT_LADDER, f"阶段 {stage}：脚手架渐退，原题不给完整解")
    if context == STUCK:
        return make(HINT_LADDER, "卡壳：按提示阶梯推进，原题不给完整解")
    return make(NEVER, "未知情境，保守 never")


@dataclass(frozen=True, slots=True)
class TutorObservation:
    """Explicit input to the Tutor controller.

    These are observations/flags, not inferred mastery.  ``answer_seen`` and
    ``independent_mode`` are safety signals supplied by the owning session.
    """

    context: str = SYSTEM_TAUGHT
    learner_stage: str | None = None
    engine_enabled: bool = False
    independent_mode: bool = False
    answer_seen: bool = False
    hints_used: int = 0
    last_outcome: str | None = None
    high_intensity_sessions: int = 0


@dataclass(frozen=True, slots=True)
class TutorDecision:
    """A replayable pedagogical decision; no mastery or verdict fields."""

    phase: str
    move: str
    answer_mode: str
    allow_full_answer: bool
    allow_worked_example: bool
    llm_generation_allowed: bool
    independent_check_due: bool
    allowed_actions: tuple[str, ...]
    rationale: str
    policy_version: str = CONTROL_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "move": self.move,
            "answer_mode": self.answer_mode,
            "allow_full_answer": self.allow_full_answer,
            "allow_worked_example": self.allow_worked_example,
            "llm_generation_allowed": self.llm_generation_allowed,
            "independent_check_due": self.independent_check_due,
            "allowed_actions": list(self.allowed_actions),
            "rationale": self.rationale,
            "policy_version": self.policy_version,
        }


def independent_check_due(
    high_intensity_sessions: int,
    *,
    cadence: int = 5,
) -> bool:
    """Return whether a no-AI transfer check should be inserted.

    The Blueprint recommends one check every 5–10 high-intensity sessions.
    The default is the deterministic lower bound; callers may configure a
    cadence in that interval without creating a random or hidden intervention.
    """

    if cadence < 5 or cadence > 10:
        raise ValueError("independent-check cadence must be between 5 and 10")
    if high_intensity_sessions < 0:
        raise ValueError("high_intensity_sessions must be non-negative")
    return high_intensity_sessions > 0 and high_intensity_sessions % cadence == 0


def decide_tutor_move(
    observation: TutorObservation,
    *,
    cadence: int = 5,
) -> TutorDecision:
    """Choose one pedagogical move from explicit session observations."""

    policy = answer_policy(
        observation.context,
        observation.learner_stage,
        enabled=observation.engine_enabled,
    )
    mode = str(policy["mode"])
    due = independent_check_due(
        observation.high_intensity_sessions,
        cadence=cadence,
    )

    # Independent mode is a hard override: it is a transfer check, not a
    # disguised hint request.  A caller may still use the contract to render a
    # neutral shell, but no LLM-generated answer may pass through it.
    if observation.independent_mode:
        move = REFLECT if observation.last_outcome else RETRIEVAL
        return TutorDecision(
            phase=DECIDE,
            move=move,
            answer_mode=NEVER,
            allow_full_answer=False,
            allow_worked_example=False,
            llm_generation_allowed=False,
            independent_check_due=due,
            allowed_actions=(RETRIEVAL, REFLECT),
            rationale="独立模式：无 AI 提示，完成检索/迁移后再记录结果",
        )

    # Seeing an answer ends the worked-example privilege for this session.
    if observation.answer_seen:
        return TutorDecision(
            phase=DECIDE,
            move=REFLECT,
            answer_mode=HINT_LADDER,
            allow_full_answer=False,
            allow_worked_example=False,
            llm_generation_allowed=True,
            independent_check_due=due,
            allowed_actions=(HINT, RETRIEVAL, REFLECT),
            rationale="学生已看过答案：停止继续示解，转向自我解释与检索",
        )

    if mode == FULL_EXAMPLE:
        return TutorDecision(
            phase=DECIDE,
            move=WORKED_EXAMPLE,
            answer_mode=mode,
            allow_full_answer=True,
            allow_worked_example=True,
            llm_generation_allowed=True,
            independent_check_due=due,
            allowed_actions=(WORKED_EXAMPLE, REFLECT),
            rationale=str(policy["rationale"]),
        )

    if observation.last_outcome in {"incorrect", "stuck"} or observation.hints_used:
        move = CONTRAST if observation.last_outcome == "incorrect" else HINT
    elif observation.learner_stage in {"retrieval", "consolidation"}:
        move = RETRIEVAL
    else:
        move = ASK
    return TutorDecision(
        phase=DECIDE,
        move=move,
        answer_mode=mode,
        allow_full_answer=False,
        allow_worked_example=False,
        llm_generation_allowed=True,
        independent_check_due=due,
        allowed_actions=(ASK, HINT, CONTRAST, RETRIEVAL, REFLECT),
        rationale=str(policy["rationale"]),
    )


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(value.split())


@dataclass(frozen=True, slots=True)
class SanitizedTutorOutput:
    text: str
    leaked: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"text": self.text, "leaked": self.leaked, "reason": self.reason}


def sanitize_tutor_output(
    text: str,
    *,
    protected_answer: str = "",
    protected_fragments: Iterable[str] = (),
    decision: TutorDecision | None = None,
    fallback: str = "请先说出你认为的下一步，并说明依据。",
) -> SanitizedTutorOutput:
    """Fail closed when a non-example Tutor output contains protected material.

    The guard is deliberately evidence-based: it compares only an answer or
    fragments supplied by the trusted question/kernel path.  It does not ask
    an LLM to decide whether its own output leaked.  A full example is allowed
    only when the decision explicitly grants that mode; independent mode can
    never grant it.
    """

    if not text:
        return SanitizedTutorOutput(text=text, leaked=False)
    if decision is not None and decision.allow_full_answer:
        return SanitizedTutorOutput(text=text, leaked=False)

    normalized_text = _normalize(text)
    candidates = [protected_answer, *protected_fragments]
    for candidate in candidates:
        normalized_candidate = _normalize(str(candidate))
        if len(normalized_candidate) >= 2 and normalized_candidate in normalized_text:
            return SanitizedTutorOutput(
                text=fallback,
                leaked=True,
                reason="protected_answer_or_fragment",
            )

    # Catch an explicit answer handoff even when a caller forgot to provide a
    # trusted fragment.  The marker alone is not enough: require a non-empty
    # value after it to avoid blocking a student-facing question such as
    # "答案是什么？".
    marker = _ANSWER_MARKER.search(text)
    if marker and text[marker.end() :].strip(" \t\r\n:：，,。.!！"):
        return SanitizedTutorOutput(
            text=fallback,
            leaked=True,
            reason="explicit_answer_marker",
        )
    return SanitizedTutorOutput(text=text, leaked=False)


__all__ = [
    "CONTROL_VERSION",
    "CONTROL_PHASES",
    "PEDAGOGICAL_MOVES",
    "TutorObservation",
    "TutorDecision",
    "SanitizedTutorOutput",
    "answer_policy",
    "decide_tutor_move",
    "independent_check_due",
    "sanitize_tutor_output",
    "OWN_HOMEWORK",
    "WRITING",
    "SYSTEM_TAUGHT",
    "STUCK",
    "NEVER",
    "FULL_EXAMPLE",
    "HINT_LADDER",
]
