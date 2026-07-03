"""作文引导 (oskill_essay_guide)

职责：语文作文引导式批改。侧重于发现问题并引导学生自我改进，严禁代写。

红队门禁（L8，2026-07-03 加）：原先只靠系统提示词约束"绝对不要直接写出"，无代码层拦截。
现加二次检测——回复中出现"帮你写/为你写/直接给"等代写交接措辞，或单条反馈过长且不含
引导问句特征（疑似整段代写内容供学生抄袭），一律拦截替换为引导语，并标记 answer_leaked。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Dict


@dataclass(frozen=True)
class EssayGuideInput:
    title: str
    content: str
    requirements: str = ""  # 写作要求
    conversation_history: List[dict] = field(default_factory=list)


@dataclass(frozen=True)
class EssayGuideResult:
    feedback: Dict[str, str]  # 维度 -> 反馈文本
    suggested_questions: List[str]  # 引导学生思考的问题
    is_completed: bool = False
    answer_leaked: bool = False  # True = 检测到疑似代写，已拦截替换（红队门禁）


_ESSAY_SYSTEM = (
    "你是一个专业的语文老师。你的任务是对学生的作文进行引导式批改。\n"
    "原则：指出问题，给出改进方向和引导性提问，但绝对不要直接写出优美的句子或整段内容供学生抄袭。\n"
    "维度包括：结构、论证/内容、表达/修辞。\n"
    "输出 JSON：\n"
    "{\n"
    '  "feedback": {"结构": "...", "论证": "...", "表达": "..."},\n'
    '  "suggested_questions": ["你觉得这里如果换一个角度写会怎样？", ...],\n'
    '  "is_completed": false\n'
    "}"
)


# 红队门禁：代写交接措辞（模型把整段/整句写好直接交给学生抄）
_HANDOFF_MARKERS = [
    "帮你写",
    "帮你改写",
    "为你写",
    "直接给你写",
    "直接帮你写",
    "可以这样写：",
    "参考范文",
    "示例段落",
    "润色后为",
    "改写如下",
    "改写为：",
    "下面是修改后",
    "这样写更好：",
    "直接抄",
    "帮你润色",
    "帮你补充这一段",
    "i'll write it for you",
    "here's the rewritten",
    "you can copy",
]
# 单条反馈/引导问超过此长度且不含引导问句特征 → 疑似整段代写内容
_HANDOFF_LEN_THRESHOLD = 80
_GUIDE_MARKERS = ("？", "?", "你觉得", "为什么", "如何", "怎么", "有没有想过")


def _looks_like_handoff(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if any(m in low for m in _HANDOFF_MARKERS):
        return True
    return len(text) > _HANDOFF_LEN_THRESHOLD and not any(g in text for g in _GUIDE_MARKERS)


async def essay_guide(
    inp: EssayGuideInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> EssayGuideResult:
    """作文引导批改。"""
    import json
    from oprim.llm._llm_complete import llm_complete

    user_msg = f"作文题目: {inp.title}\n写作要求: {inp.requirements}\n学生作文正文: {inp.content}\n"

    messages = list(inp.conversation_history)
    messages.append({"role": "user", "content": user_msg})

    response = await llm_complete(messages, caller=caller, system=_ESSAY_SYSTEM, model=model)

    raw = response.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    feedback: Dict[str, str] = data.get("feedback", {})
    suggested_questions: List[str] = data.get("suggested_questions", [])

    # 红线二次检测：整段代写拦截（不依赖系统提示词是否被绕过）
    answer_leaked = False
    safe_feedback: Dict[str, str] = {}
    for dim, text in feedback.items():
        if _looks_like_handoff(text):
            answer_leaked = True
            safe_feedback[dim] = (
                "这一部分老师不能直接帮你写，你可以先说说自己的思路，我们一起讨论怎么改？"
            )
        else:
            safe_feedback[dim] = text
    safe_questions: List[str] = []
    for q in suggested_questions:
        if _looks_like_handoff(q):
            answer_leaked = True
            safe_questions.append("你觉得这一段可以怎么调整？")
        else:
            safe_questions.append(q)

    return EssayGuideResult(
        feedback=safe_feedback,
        suggested_questions=safe_questions,
        is_completed=data.get("is_completed", False),
        answer_leaked=answer_leaked,
    )


__version__ = "0.2.0"  # 红队门禁：代写检测（L8，2026-07-03）
