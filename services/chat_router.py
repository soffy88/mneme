"""chat_router —— C1（W2C）/v1/chat/turn：学生对话入口，接 intent_router + tutor_loop。

Layer4 服务层（有 DB，供鉴权/取 persona/取路径用）；实际推理循环委托给
``mneme_agent.assembly.chat_loop.run_chat_turn``（零 DB，FC-5）。``tool_chat_turn``
持全部编排逻辑、可脱 HTTP 直测（对照 mcp_router.py 的 tool_*/mcp_* 分层惯例）；
HTTP 端点只做鉴权 + 组装真 Qwen caller。

依赖 mneme_core + mneme_agent + oservi，跟 mcp_router 同一"未装则优雅降级"惯例
（main.py try/except ImportError 挂载）。
"""

from __future__ import annotations

import os
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

    return await run_chat_turn(
        student_id=str(student_id),
        kc_ids=kc_ids,
        history=history or [],
        message=message,
        llm_caller=loop_caller,
        classify_llm=classify_llm,
        persona_prompt_block=persona_block,
        auth_token=auth_token,
    )


async def _classify_llm(prompt: str) -> str:
    """intent_router 的注入 LLM：无 key 时保守回落 free_qa，不阻断对话。"""
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        return '{"mode": "free_qa"}'
    from services.providers.qwenvl_caller import QwenTextCaller

    caller = QwenTextCaller(
        api_key=key, model=os.environ.get("QWEN_MODEL", "qwen-plus")
    )
    out = await caller(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        enable_thinking=False,  # 分类任务无需思维链（AA.8 同理）
    )
    return str(out.get("content", ""))


@router.post("/turn")
async def chat_turn(
    req: ChatTurnReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    bearer_token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    _ensure_student_self(current_user, req.student_id)

    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise HTTPException(503, "chat 暂不可用（缺 LLM key）")

    from mneme_agent.qwen_llm import QwenLoopCaller

    loop_caller = QwenLoopCaller(api_key=key, model=os.environ.get("QWEN_MODEL"))

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
