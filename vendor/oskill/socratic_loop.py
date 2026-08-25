"""Orchestrate a multi-turn Socratic tutoring loop.

Composes oprim.socratic_turn and oprim.verify_step.
Red line: If LLM reveals correct_answer, filter and retry with generic prompt.
Hardened 2026-07-03 (L8 红队门禁): whitespace-normalized comparison to catch
spacing-obfuscated leaks (e.g. "x = 2" vs stored "x=2").

Version: oskill v3.21.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SocraticLoopInput:
    """Input for a Socratic loop session.

    Attributes
    ----------
    question : str
        The math question being tutored.
    correct_answer : str
        The correct answer. MUST NOT be revealed to the student.
    max_turns : int
        Maximum number of dialogue turns.
    kc_ids : list[str]
        Knowledge components the question targets.
    caller : Any
        LLM caller (injected).
    model : str
    """

    question: str
    correct_answer: str
    caller: Any
    max_turns: int = 5
    kc_ids: list[str] = field(default_factory=list)
    model: str = "claude-sonnet-4-6"


@dataclass
class SocraticLoopState:
    """Mutable state for a Socratic loop session."""

    question: str
    correct_answer: str
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    resolved: bool = False
    violation_count: int = 0


@dataclass(frozen=True)
class SocraticTurnOutput:
    """Output of a single processed Socratic turn."""

    assistant_text: str
    step_check_triggered: bool
    answer_leaked: bool
    turn_number: int


async def process_socratic_turn(
    state: SocraticLoopState,
    student_message: str,
    *,
    caller: Any,
    kc_ids: list[str] | None = None,
    model: str = "claude-sonnet-4-6",
    hint_level: int = 1,
    learner_profile: str | None = None,
    textbook_id: str = "",
) -> SocraticTurnOutput:
    """Process one student turn in the Socratic loop.

    Red line: if the LLM's response contains correct_answer, replace with
    a generic follow-up question and log the violation.

    Parameters
    ----------
    state : SocraticLoopState
    student_message : str
    caller : Any
    kc_ids : list[str] | None
    model : str
    hint_level : int

    Returns
    -------
    SocraticTurnOutput
    """
    from oprim.socratic_turn import socratic_turn, SocraticTurnInput

    # RAG Retrieval
    textbook_context = ""
    if textbook_id:
        try:
            from oprim.retrieve_chunks import retrieve_chunks, format_chunks_as_context
            from obase.db import SessionLocal

            async with SessionLocal() as db:
                chunks = await retrieve_chunks(
                    db,
                    file_id=textbook_id,
                    query=student_message,
                    top_k=3,
                    kc_ids=kc_ids,
                )
                if chunks:
                    textbook_context = format_chunks_as_context(chunks)
        except Exception as e:
            logger.error(f"Failed to retrieve textbook chunks for socratic_loop: {e}")

    state.messages.append({"role": "user", "content": student_message})
    state.turn_count += 1

    inp = SocraticTurnInput(
        question=state.question,
        correct_answer=state.correct_answer,
        student_last_message=student_message,
        conversation_history=state.messages[:-1],  # history before this turn
        kc_ids=kc_ids or [],
        hint_level=hint_level,
        learner_profile=learner_profile,
        textbook_context=textbook_context,
    )

    result = await socratic_turn(inp, caller=caller, model=model)
    text = result.text

    # Red line: use the shared deterministic Tutor output guard.  Socratic
    # turns are always a hint-ladder context, so the guard is fail-closed even
    # when a future caller changes the surrounding prompt/role wording.
    from mneme_core.tutor_control import (
        TutorObservation,
        decide_tutor_move,
        sanitize_tutor_output,
    )

    decision = decide_tutor_move(
        TutorObservation(context="stuck", engine_enabled=True)
    )
    guarded = sanitize_tutor_output(
        text,
        protected_answer=state.correct_answer or "",
        decision=decision,
        fallback="这道题你再想想，思路是什么？",
    )
    answer_leaked = guarded.leaked
    if answer_leaked:
        state.violation_count += 1
        logger.warning(
            "socratic red-line: answer leaked in turn %d (answer=%r, preview=%r)",
            state.turn_count,
            (state.correct_answer or "")[:20],
            text[:60],
        )
        text = guarded.text

    state.messages.append({"role": "assistant", "content": text})

    return SocraticTurnOutput(
        assistant_text=text,
        step_check_triggered=result.step_check_triggered,
        answer_leaked=answer_leaked,
        turn_number=state.turn_count,
    )


def create_socratic_state(question: str, correct_answer: str) -> SocraticLoopState:
    """Create a fresh Socratic loop state."""
    return SocraticLoopState(
        question=question,
        correct_answer=correct_answer,
    )
