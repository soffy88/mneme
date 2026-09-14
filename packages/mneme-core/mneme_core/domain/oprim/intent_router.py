"""intent_router —— 单 LLM 调用：判断学生这句话是自由问答还是想转 Mastery Path 练习。

C1（W2C）。FC-6 分类筛判定：带 Mneme 模式假设（"转 Mastery Path"是 Mneme 特有概念、
不是通用 chat 概念）→ 私有，不进共享 platform/3O 主库。

单 LLM 调用 = oprim（不是 oskill——复杂 ≠ 层级）。``llm`` 由调用方注入（本模块零 IO、
零网络依赖，对照 mneme-core 既有 ``qualitative_verifier`` 同一惯例：纯函数 + 注入
LLMCaller，可测、不依赖具体 provider）。

fail-safe：LLM 输出解析失败、字段缺失或不合法 → 一律回落 ``free_qa``——宁可少路由
一次练习，也不能误判打断正常对话。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

ChatMode = Literal["free_qa", "practice"]

_PROMPT_TEMPLATE = (
    "你在判断一句中国中小学生跟学习助手说的话，属于哪种模式。只输出严格 JSON，"
    '不要任何解释：{{"mode": "free_qa" 或 "practice", "kc_hint": 提取的主题词或 null}}\n\n'
    "practice：学生明确想做练习/测验/复习，例如"
    "「我想练函数」「想练习一元二次方程」「帮我出几道题」「考我一下」「复习一下三角函数」。\n"
    "free_qa：其他任何情况，例如提问概念、闲聊、求助解题思路。\n\n"
    "学生说：{message}"
)


@dataclass(frozen=True)
class ChatIntent:
    mode: ChatMode
    kc_hint: Optional[str] = None


def _extract_json(text: str) -> str:
    """从模型输出里尽量抠出 JSON（兼容 ```json 代码块 / 裸 JSON）。"""
    t = text.strip()
    if "```json" in t:
        return t.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in t:
        return t.split("```", 1)[1].split("```", 1)[0].strip()
    return t


async def classify_chat_intent(
    message: str, *, llm: Callable[[str], Awaitable[str]]
) -> ChatIntent:
    """判断 message 的模式；llm 是 (prompt: str) -> 模型文本输出 的注入函数。

    任何异常（llm 调用失败、JSON 解析失败、字段非法）→ 回落 ``ChatIntent(mode="free_qa")``。
    """
    try:
        raw = await llm(_PROMPT_TEMPLATE.format(message=message))
        data = json.loads(_extract_json(raw))
        mode = data.get("mode")
        if mode not in ("free_qa", "practice"):
            return ChatIntent(mode="free_qa")
        kc_hint = data.get("kc_hint")
        return ChatIntent(mode=mode, kc_hint=str(kc_hint) if kc_hint else None)
    except Exception:
        return ChatIntent(mode="free_qa")
