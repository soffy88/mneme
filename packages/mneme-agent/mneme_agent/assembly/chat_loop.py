"""chat_loop —— C1（W2C）chat 工作区的循环装配。

intent_router 判模式（自由问答 / 转 Mastery Path）+ **复用**已装配的 oservi
AgenticLoop（tutor_loop.build_tutor_loop）驱动 free_qa 模式——**禁另起循环**
（FC-4）：practice 模式完全不进循环，只返回 handoff，由前端导航 /studio/learn
去驱动既有的路径学习流程（NextObjective/RequestQuestion 自然接手，不重造）。

**agent 进程零 mneme-DB**（FC-5）：本模块无任何 DB import，工具全走 HTTP（继承
tutor_loop 的既有 8 callable，含 AA.1 起必带的 auth_token——转发学生自己的
token，不单独铸造）。tutor_loop 的工具集里没有 RequestQuestion——bank 的
expected 从不进入这条对话路径的上下文，红线天然成立（不是额外补的）。

多轮对话：``AgenticLoop.session()`` 本身不持久化跨调用历史（每次全新 SessionState）
——调用方（本模块）负责把历史拼进单次 task 文本；真正的历史存储/持久化留 C5
（mneme-agent MCP wiring 完成后再接，本轮 agent 进程仍不持久化任何东西）。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from mneme_core.oprim.intent_router import classify_chat_intent

from mneme_agent.assembly.tutor_loop import (
    DEFAULT_API_BASE,
    LoopLLM,
    VerifierLLM,
    build_tutor_loop,
)

ClassifyLLM = Callable[[str], Awaitable[str]]


def _render_task(history: list[dict], message: str) -> str:
    """历史对话 + 最新消息 拼成单个 task 字符串（session() 无原生多轮历史参数）。"""
    lines = [f"{h['role']}: {h['content']}" for h in history]
    lines.append(f"user: {message}")
    return "\n".join(lines)


async def run_chat_turn(
    *,
    api_base: str = DEFAULT_API_BASE,
    student_id: str,
    kc_ids: list[str],
    history: Optional[list[dict]] = None,
    message: str,
    llm_caller: LoopLLM,
    classify_llm: ClassifyLLM,
    persona_prompt_block: str = "",
    verifier_llm: Optional[VerifierLLM] = None,
    auth_token: Optional[str] = None,
    max_iterations: int = 40,
) -> dict:
    """跑一轮 chat：先分流意图，practice 直接 handoff，free_qa 才进 tutor_loop。

    Returns:
        practice: {"action": "goto_mastery_path", "kc_hint": str|None, "reply": str}
        free_qa : {"action": "continue", "reply": str, "status": str}
    """
    intent = await classify_chat_intent(message, llm=classify_llm)

    if intent.mode == "practice":
        reply = (
            f"好的，我们去练习「{intent.kc_hint}」相关的内容吧！"
            if intent.kc_hint
            else "好的，我们去练习吧！"
        )
        return {
            "action": "goto_mastery_path",
            "kc_hint": intent.kc_hint,
            "reply": reply,
        }

    loop = build_tutor_loop(
        api_base=api_base,
        student_id=student_id,
        kc_ids=kc_ids,
        llm_caller=llm_caller,
        verifier_llm=verifier_llm,
        auth_token=auth_token,
        max_iterations=max_iterations,
    )
    task = _render_task(history or [], message)
    result = await loop.session(task=task, system_prompt=persona_prompt_block)
    return {
        "action": "continue",
        "reply": result["result"],
        "status": result["status"],
    }
