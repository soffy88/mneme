"""Blueprint P4 Tutor control contract and leakage guard tests."""

from __future__ import annotations

import pytest

from mneme_core.tutor_control import (
    FULL_EXAMPLE,
    HINT_LADDER,
    NEVER,
    RETRIEVAL,
    REFLECT,
    SYSTEM_TAUGHT,
    TutorObservation,
    answer_policy,
    decide_tutor_move,
    independent_check_due,
    sanitize_tutor_output,
)


def test_control_uses_worked_example_only_for_new_system_taught_content():
    decision = decide_tutor_move(
        TutorObservation(
            context=SYSTEM_TAUGHT,
            learner_stage="worked_example",
            engine_enabled=True,
        )
    )

    assert decision.move == "worked_example"
    assert decision.answer_mode == FULL_EXAMPLE
    assert decision.allow_full_answer is True
    assert decision.policy_version == "tutor-control/v1"


def test_seen_answer_and_independent_mode_override_example_privilege():
    seen = decide_tutor_move(
        TutorObservation(
            context=SYSTEM_TAUGHT,
            learner_stage="worked_example",
            engine_enabled=True,
            answer_seen=True,
        )
    )
    independent = decide_tutor_move(
        TutorObservation(
            context=SYSTEM_TAUGHT,
            learner_stage="worked_example",
            engine_enabled=True,
            independent_mode=True,
        )
    )

    assert seen.answer_mode == HINT_LADDER
    assert seen.move == REFLECT
    assert independent.answer_mode == NEVER
    assert independent.llm_generation_allowed is False
    assert independent.allowed_actions == (RETRIEVAL, REFLECT)


def test_control_selects_retrieval_after_late_stage_and_reports_transfer_slot():
    decision = decide_tutor_move(
        TutorObservation(
            context=SYSTEM_TAUGHT,
            learner_stage="consolidation",
            engine_enabled=True,
            high_intensity_sessions=10,
        )
    )

    assert decision.move == RETRIEVAL
    assert decision.independent_check_due is True


def test_independent_cadence_is_explicit_and_bounded():
    assert independent_check_due(5) is True
    assert independent_check_due(9) is False
    assert independent_check_due(10, cadence=10) is True
    with pytest.raises(ValueError):
        independent_check_due(5, cadence=4)


def test_output_guard_catches_normalized_answer_and_explicit_handoff():
    decision = decide_tutor_move(
        TutorObservation(context="stuck", engine_enabled=True)
    )
    normalized = sanitize_tutor_output(
        "把空格去掉后，直接得到 x = 2。",
        protected_answer="x=2",
        decision=decision,
    )
    marker = sanitize_tutor_output(
        "正确答案是：先写出最终结果。",
        decision=decision,
    )

    assert normalized.leaked is True
    assert normalized.reason == "protected_answer_or_fragment"
    assert "x = 2" not in normalized.text
    assert marker.leaked is True
    assert marker.reason == "explicit_answer_marker"


def test_output_guard_allows_verified_worked_example_only_when_policy_grants_it():
    decision = decide_tutor_move(
        TutorObservation(
            context=SYSTEM_TAUGHT,
            learner_stage="worked_example",
            engine_enabled=True,
        )
    )
    result = sanitize_tutor_output(
        "这是系统同构题的完整示例：x=2。",
        protected_answer="x=2",
        decision=decision,
    )

    assert result.leaked is False
    assert result.text.endswith("x=2。")


def test_answer_policy_compatibility_import_remains_single_source():
    from oprim.answer_policy import answer_policy as legacy_policy

    assert legacy_policy(SYSTEM_TAUGHT, "worked_example", enabled=True) == answer_policy(
        SYSTEM_TAUGHT, "worked_example", enabled=True
    )


@pytest.mark.asyncio
async def test_local_agent_loop_guards_text_before_emitting_or_continuing():
    from mneme_agent.assembly.local_agentic_loop import LocalAgenticLoop, ToolSpec

    async def caller(**_kwargs):
        return {
            "content": [{"type": "text", "text": "答案是 x=2。"}],
            "stop_reason": "end_turn",
            "usage": {},
        }

    emitted: list[str] = []
    loop = LocalAgenticLoop(max_iterations=1)
    loop.assemble(
        llm_caller=caller,
        tools=[
            ToolSpec(
                name="noop",
                description="noop",
                input_schema={"type": "object"},
                callable=lambda _input: None,
            )
        ],
        output_guard=lambda text: "已拦截" if "答案是" in text else text,
    )

    result = await loop.session(task="帮我做题", on_token=emitted.append)

    assert result["result"] == "已拦截"
    assert emitted == ["已拦截"]


@pytest.mark.asyncio
async def test_tutor_loop_defaults_to_conservative_output_guard():
    from mneme_agent.assembly.tutor_loop import build_tutor_loop

    async def caller(**_kwargs):
        return {
            "content": [{"type": "text", "text": "答案是 x=2。"}],
            "stop_reason": "end_turn",
            "usage": {},
        }

    loop = build_tutor_loop(
        student_id="student-1",
        kc_ids=["ku-1"],
        llm_caller=caller,
    )
    result = await loop.session(task="请帮我做题")

    assert result["status"] == "completed"
    assert "答案是" not in result["result"]
    assert result["result"] == "请先说出你认为的下一步，并说明依据。"
