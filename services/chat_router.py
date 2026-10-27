"""chat_router —— C1（W2C）/v1/chat/turn：学生对话入口，接 intent_router + tutor_loop。

Layer4 服务层（有 DB，供鉴权/取 persona/取路径用）；实际推理循环委托给
``mneme_agent.assembly.chat_loop.run_chat_turn``（零 DB，FC-5）。``tool_chat_turn``
持全部编排逻辑、可脱 HTTP 直测（对照 mcp_router.py 的 tool_*/mcp_* 分层惯例）；
HTTP 端点只做鉴权 + 组装已配置的本机/云端 caller。

依赖 mneme_core + mneme_agent；循环骨架由 mneme-agent 仓内实现，chat 不依赖可选
oservi 挂载。
"""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_agent.assembly.chat_loop import run_chat_turn

from obase.db import get_db
from services import persona_store
from services.auth_deps import _ensure_student_self, get_current_user, oauth2_scheme
from services.mcp_router import tool_get_path, tool_get_persona
from services.provenance import (
    STEERING_NOTICE,
    scan_injected_instructions,
    scan_result_to_dict,
)
from services.models import User

router = APIRouter(prefix="/v1/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatTurnReq(BaseModel):
    student_id: uuid.UUID
    message: str
    history: list[ChatMessage] = []
    persona_slug: Optional[str] = None
    kc_ids: Optional[list[str]] = None


async def tool_chat_turn(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    message: str,
    history: Optional[list[dict]] = None,
    persona_slug: Optional[str] = None,
    kc_ids: Optional[list[str]] = None,
    loop_caller: Any,
    classify_llm: Callable[[str], Awaitable[str]],
    auth_token: Optional[str] = None,
    extra_system: str = "",
    max_iterations: int = 40,
    strict_provenance: bool = False,
) -> dict:
    """编排：取 KC 候选池（不传则用 GetPath 默认路径）→ 取 persona（C3）渲染成
    system prompt 块 → 调 run_chat_turn（零 DB，FC-5）。可脱 HTTP 直测——真/假
    caller 皆可注入。

    auth_token：/mcp/* 自 AA.1 起每端点要求 JWT——转发发起本轮对话的学生自己的
    token（HTTP 端点从 Authorization 头取，直调时可不传/传测试 token）。
    """
    if kc_ids is None:
        path = await tool_get_path(db, student_id)
        kc_ids = path["kc_ids"]

    # 复用 tool_get_persona（单源：未知 slug 回落默认人格的逻辑只写一处）
    persona_result = await tool_get_persona(
        db, persona_slug or persona_store.DEFAULT_PERSONA_SLUG
    )
    persona_block = persona_result.get("prompt_block", "")
    if extra_system:  # 语音/陪练：安全提示与人格规则追加在 persona 之后（规则优先于语气）
        persona_block = f"{persona_block}\n\n{extra_system}".strip()

    result = await run_chat_turn(
        student_id=str(student_id),
        kc_ids=kc_ids,
        history=history or [],
        message=message,
        llm_caller=loop_caller,
        classify_llm=classify_llm,
        persona_prompt_block=persona_block,
        auth_token=auth_token,
        max_iterations=max_iterations,
    )
    if not isinstance(result, dict):
        return result
    # 溯源门禁（嫁接 1）：循环当前只回纯文本，尚无分段标签，故此处如实
    # 标注 gate=unlabeled/certified=False，不谎称已标注；导航回复（去练
    # 习）不含事实主张，豁免。strict_provenance=True 时未认证的知识回答
    # 直接拦截、不交付原文——生产切 strict 前须先让循环输出分段标签。
    hits = scan_injected_instructions(message)
    reply_text = result.get("reply")
    if reply_text:
        hits += scan_injected_instructions(str(reply_text))
    action = result.get("action")
    if action == "goto_mastery_path":
        gate, certified = "exempt", True
    else:
        gate, certified = "unlabeled", False
    provenance = {
        "gate": gate,
        "certified": certified,
        "steering_hits": scan_result_to_dict(hits),
        "notice": STEERING_NOTICE if hits else None,
    }
    if strict_provenance and not certified:
        return {
            **result,
            "reply": "本轮回答未完成来源标注，已按门禁拦截，未交付原文。",
            "provenance": {**provenance, "refused": True},
        }
    return {**result, "provenance": provenance}


async def _classify_llm(prompt: str) -> str:
    """intent_router 的注入 LLM：无 key 时保守回落 free_qa，不阻断对话。"""
    try:
        from services.providers.setup import get_text_caller

        out = await get_text_caller()(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            enable_thinking=False,  # 分类任务无需思维链（AA.8 同理）
        )
        return str(out.get("content", ""))
    except Exception:  # noqa: BLE001 - intent safely falls back to free_qa
        return '{"mode": "free_qa"}'


@router.post("/turn")
async def chat_turn(
    req: ChatTurnReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    bearer_token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    _ensure_student_self(current_user, req.student_id)

    try:
        from services.providers.setup import get_agent_loop_caller

        loop_caller = get_agent_loop_caller()
    except Exception as exc:  # noqa: BLE001 - safe provider boundary
        raise HTTPException(503, "chat 暂不可用（provider unavailable）") from exc

    return await tool_chat_turn(
        db,
        req.student_id,
        message=req.message,
        history=[h.model_dump() for h in req.history],
        persona_slug=req.persona_slug,
        kc_ids=req.kc_ids,
        loop_caller=loop_caller,
        classify_llm=_classify_llm,
        # 转发学生自己这次请求带的 token——tutor_loop 的 /mcp/* 工具调用要用
        # （AA.1 起每端点要求 JWT），不单独铸造。
        auth_token=bearer_token,
    )
