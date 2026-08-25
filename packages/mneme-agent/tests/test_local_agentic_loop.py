from __future__ import annotations

import json

import pytest

from mneme_agent.assembly.local_agentic_loop import LocalAgenticLoop, ToolSpec


@pytest.mark.asyncio
async def test_local_loop_runs_tool_call_without_oservi() -> None:
    seen: list[dict] = []
    calls = 0

    async def remember(payload: dict) -> dict:
        seen.append(payload)
        return {"saved": True, "note": payload["note"]}

    async def caller(*, messages, tools, max_tokens, thinking_budget, system):
        nonlocal calls
        del max_tokens, thinking_budget
        calls += 1
        assert tools[0]["name"] == "Remember"
        assert "善学记" in system
        if calls == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Remember",
                        "input": {"note": "函数定义"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"][0]["type"] == "tool_result"
        return {
            "content": [{"type": "text", "text": "已记下。"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }

    loop = LocalAgenticLoop(max_iterations=3).assemble(
        llm_caller=caller,
        tools=[
            ToolSpec(
                name="Remember",
                description="记忆",
                input_schema={
                    "type": "object",
                    "properties": {"note": {"type": "string"}},
                    "required": ["note"],
                },
                callable=remember,
            )
        ],
    )

    result = await loop.session("请记住函数定义")

    assert result["status"] == "completed"
    assert result["result"] == "已记下。"
    assert result["iterations"] == 2
    assert seen == [{"note": "函数定义"}]
    assert json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_local_loop_contains_tool_errors_in_observation() -> None:
    async def fail(_payload: dict) -> None:
        raise RuntimeError("tool unavailable")

    calls = 0

    async def caller(*, messages, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-2",
                        "name": "Fail",
                        "input": {},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {},
            }
        assert "tool unavailable" in messages[-1]["content"][0]["content"]
        return {
            "content": [{"type": "text", "text": "我会稍后再试。"}],
            "stop_reason": "end_turn",
            "usage": {},
        }

    loop = LocalAgenticLoop().assemble(
        llm_caller=caller,
        tools=[
            ToolSpec(
                name="Fail",
                description="失败工具",
                input_schema={"type": "object"},
                callable=fail,
            )
        ],
    )

    result = await loop.session("测试工具失败")

    assert result["status"] == "completed"
    assert result["result"] == "我会稍后再试。"
