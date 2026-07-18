"""chat_loop —— C1（W2C）：intent 分流 + 复用 tutor_loop（FC-4 禁另起循环）。

真 oservi AgenticLoop（practice 分支必须完全不触发它——用会抛异常的假 llm_caller
证明"根本没调用"，而不仅仅是"调用了但没被使用"）。agent 零 DB，工具全走 HTTP，但
free_qa 分支这里用脚本化 llm_caller 直接一轮结束，不需要真跑 /mcp/*。
"""

from __future__ import annotations

import pytest

pytest.importorskip("oservi")
pytest.importorskip("mneme_core")

from mneme_agent.assembly.chat_loop import run_chat_turn  # noqa: E402

KC_IDS = ["renjiao-math-g10-a-ku001"]


def _classify_llm(response: str):
    async def llm(prompt: str) -> str:
        del prompt
        return response

    return llm


async def _exploding_llm_caller(**kwargs):
    raise AssertionError(
        f"tutor_loop 的 llm_caller 不该被调用（practice 分支必须完全不进循环，FC-4）: {kwargs}"
    )


def _one_shot_llm_caller(captured: dict):
    """脚本化 llm_caller：立即返回终止文本（一轮结束），并把收到的 system 记进 captured。"""

    async def llm(
        *, messages, tools=None, max_tokens=8192, thinking_budget=None, system=None
    ):
        del messages, tools, max_tokens, thinking_budget
        captured["system"] = system
        return {
            "content": [{"type": "text", "text": "好的，我们来看看这道题。"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    return llm


@pytest.mark.asyncio
async def test_practice_intent_never_invokes_tutor_loop():
    result = await run_chat_turn(
        student_id="s1",
        kc_ids=KC_IDS,
        message="我想练函数",
        llm_caller=_exploding_llm_caller,
        classify_llm=_classify_llm('{"mode": "practice", "kc_hint": "函数"}'),
    )
    assert result["action"] == "goto_mastery_path"
    assert result["kc_hint"] == "函数"
    assert "函数" in result["reply"]


@pytest.mark.asyncio
async def test_free_qa_invokes_tutor_loop_with_persona_system_prompt():
    captured: dict = {}
    result = await run_chat_turn(
        student_id="s1",
        kc_ids=KC_IDS,
        message="什么是函数？",
        llm_caller=_one_shot_llm_caller(captured),
        classify_llm=_classify_llm('{"mode": "free_qa", "kc_hint": null}'),
        persona_prompt_block="## 当前人格：鼓励型伙伴\n独特语气标记XYZ",
    )
    assert result["action"] == "continue"
    assert result["status"] == "completed"
    assert result["reply"] == "好的，我们来看看这道题。"
    assert "独特语气标记XYZ" in captured["system"]


@pytest.mark.asyncio
async def test_multi_turn_history_is_included_in_task():
    """对话可多轮：历史被拼进 task（AgenticLoop 本身无跨调用历史，调用方负责拼装）。"""
    captured: dict = {}

    async def capturing_llm(
        *, messages, tools=None, max_tokens=8192, thinking_budget=None, system=None
    ):
        del tools, max_tokens, thinking_budget, system
        captured["messages"] = messages
        return {
            "content": [{"type": "text", "text": "继续。"}],
            "stop_reason": "end_turn",
            "usage": {},
        }

    history = [
        {"role": "user", "content": "什么是函数？"},
        {"role": "assistant", "content": "函数是一种对应关系。"},
    ]
    await run_chat_turn(
        student_id="s1",
        kc_ids=KC_IDS,
        history=history,
        message="能举个例子吗？",
        llm_caller=capturing_llm,
        classify_llm=_classify_llm('{"mode": "free_qa"}'),
    )
    task_text = captured["messages"][0]["content"]
    assert "什么是函数？" in task_text
    assert "函数是一种对应关系。" in task_text
    assert "能举个例子吗？" in task_text
