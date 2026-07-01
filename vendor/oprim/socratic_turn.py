"""Generate a single Socratic dialogue turn for math tutoring.

Async, single LLM call.  Must NOT reveal the correct answer.
Returns SocraticTurnResult — if response leaks the answer, caller filters it.

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from oprim.types import SocraticTurnResult


@dataclass
class SocraticTurnInput:
    """Input for a single Socratic dialogue turn.

    Attributes
    ----------
    question : str
        The math question being discussed.
    correct_answer : str
        The correct answer (MUST NOT be revealed to the student).
    conversation_history : list[dict]
        Prior turns as [{"role": "user"|"assistant", "content": str}].
    student_last_message : str
        Student's most recent message.
    kc_ids : list[str]
        Knowledge components this question targets.
    hint_level : int
        0 = no hints, 1 = gentle prompt, 2 = structural hint, 3 = explicit hint.
    system : str | None
        Optional system prompt override.
    """

    question: str
    correct_answer: str
    student_last_message: str
    conversation_history: list[dict] = field(default_factory=list)
    kc_ids: list[str] = field(default_factory=list)
    hint_level: int = 1
    system: str | None = None


_SOCRATIC_SYSTEM = (
    "You are a Socratic math tutor. Guide the student with questions and hints "
    "to discover the answer themselves. NEVER reveal the correct answer directly. "
    "Ask probing questions that help them think through the problem step by step. "
    "If the student is stuck, provide a gentle structural hint without giving away "
    "the answer. Keep responses concise (2-3 sentences max). "
    "Respond in the same language as the student."
)


async def socratic_turn(
    inp: SocraticTurnInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 512,
) -> SocraticTurnResult:
    """Generate one Socratic tutoring turn.

    The correct_answer is passed to the system for context but the LLM is
    instructed never to reveal it.  The response text is further filtered
    by the caller (oskill layer) to ensure compliance.

    Parameters
    ----------
    inp : SocraticTurnInput
    caller : Any
    model : str
    max_tokens : int

    Returns
    -------
    SocraticTurnResult
    """
    from oprim.llm._llm_complete import llm_complete

    hint_map = {
        0: "提问引导，不提示",
        1: "给出温和提示",
        2: "给出结构性提示",
        3: "给出明确提示但不给答案",
    }
    hint_desc = hint_map.get(inp.hint_level, "温和提示")

    system = inp.system or (
        _SOCRATIC_SYSTEM + f"\n\n当前题目: {inp.question}"
        f"\n提示级别: {hint_desc}"
        f"\n[仅供参考，绝对不要透露] 正确答案: {inp.correct_answer}"
    )

    messages = list(inp.conversation_history)
    messages.append({"role": "user", "content": inp.student_last_message})

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )

        text = response.text.strip()

        # Detect if step_check should be triggered (student made an error)
        step_check_triggered = any(
            kw in inp.student_last_message.lower()
            for kw in ["我算了", "我得到", "答案是", "结果是", "=", "等于"]
        )

        return SocraticTurnResult(
            text=text,
            step_check_triggered=step_check_triggered,
        )

    except Exception as exc:
        return SocraticTurnResult(
            text="这道题你再想想，思路是什么？",
            step_check_triggered=False,
        )
