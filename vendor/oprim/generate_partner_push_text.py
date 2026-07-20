"""oprim.generate_partner_push_text — W5 A3 心跳：单次 LLM 调用生成推送文案。

单 LLM 调用 = oprim（非 oskill——复杂度不等于层级）。无 llm_caller 或调用失败
时回落到确定性模板（同 tasks/partner_tasks.py 既有 f-string 风格），保证任何
环境下都产出可推送文本，不因 LLM 不可用/未配置而丢消息。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

LLMCaller = Callable[..., Awaitable[dict[str, Any]]]

_FALLBACK_TEMPLATE = (
    "你好，{name}：根据记忆曲线，你有 {due_count} 道错题到了最佳的复习时间。"
    "趁热打铁，花几分钟清空复习队列，让短期记忆转化为长期记忆吧！"
)


async def generate_push_text(
    *,
    name: str,
    due_count: int,
    llm_caller: Optional[LLMCaller] = None,
) -> str:
    """生成一条推送文案。llm_caller 为 None（默认）时直接走确定性模板。"""
    if llm_caller is None:
        return _FALLBACK_TEMPLATE.format(name=name or "同学", due_count=due_count)

    prompt = (
        f"你是一位温暖、简洁的学习助理。学生「{name or '同学'}」有 {due_count} "
        f"道错题到了记忆曲线复习最佳时间点。写一句不超过 60 字的中文推送提醒，"
        f"语气鼓励、不说教，不要输出任何解释或前后缀，只输出这句提醒本身。"
    )
    try:
        result = await llm_caller(
            messages=[{"role": "user", "content": prompt}],
            system="你是一位温暖简洁的学习助理，只输出要求的提醒文本本身。",
            max_tokens=120,
        )
        text = (result.get("content") or "").strip()
        if text:
            return text
    except Exception as e:  # noqa: BLE001 — LLM 失败回落模板，不丢推送
        logger.warning(f"generate_push_text LLM error: {e}")

    return _FALLBACK_TEMPLATE.format(name=name or "同学", due_count=due_count)
