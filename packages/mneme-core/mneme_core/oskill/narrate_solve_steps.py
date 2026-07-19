"""narrate_solve_steps —— Solve 模式讲解层（W4 §2）。

给定内核真实求解结果（SolveResult 的原始 answer/steps，非 LLM 二次推导），
LLM 只负责把这些已经确定性算好的步骤转述成学生能读懂的自然语言讲解——不
参与求解、不参与判断对错（SV-2/SV-4 红线）。讲解是纯附加字段，调用方
（vendor/omodul.solve_problem）必须原样透传内核的 answer/steps，绝不用
LLM 输出替换/覆盖它们——这条红线在调用方的返回结构里落地（narration 与
answer/steps 是并列的独立字段），本元素自身不做任何"回填/纠正答案"的事。

组合 ≥2 oprim 形态：(1) 步骤渲染成 LLM 可读文本；(2) 注入的 LLM 调用 +
容错兜底（LLM 失败时兜底为"逐步直读"内核步骤，不让整条链路因为讲解失败
而拿不到任何解释——同 book_ideation 的"失败降级不抛异常"红线）。

FC-6：带"面向学生讲解"这个 Mneme 教学场景假设，留 mneme-core 私有。
"""

from __future__ import annotations

from typing import Optional, Protocol


class LLMCaller(Protocol):
    """注入式异步 LLM 调用契约，返回 {"content": <原始补全文本>}。"""

    async def __call__(
        self,
        *,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 800,
    ) -> dict: ...


_SYSTEM_PROMPT = (
    "你是中国中小学数学老师。下面给出一道题的确定性求解步骤和最终答案——"
    "这些都已经算好、是正确的，你不需要也不能重新计算或修改它们，只需要把"
    "这些步骤转述成学生能读懂的自然语言讲解，帮助学生理解每一步在做什么、"
    "为什么这么做。绝不能给出与提供的步骤/答案不同的数值结果，不要在讲解里"
    "编造原始步骤里没有的计算过程。"
)


def _render_steps(kernel: str, task: str, answer: str, steps: list[dict]) -> str:
    lines = [
        f"内核：{kernel}（任务：{task or '（无）'}）",
        f"最终答案：{answer}",
        "",
        "求解步骤：",
    ]
    for s in steps:
        lines.append(
            f"步骤{s.get('step_number')}：{s.get('description')} | "
            f"{s.get('expression')} -> {s.get('result')}"
        )
    return "\n".join(lines)


def _fallback_narration(steps: list[dict], answer: str) -> str:
    """LLM 失败时的兜底：逐步直读内核步骤，不让链路因讲解失败而拿不到任何
    解释——内容仍然 100% 来自内核真实输出，只是没有 LLM 的自然语言转述。
    """
    lines = [
        f"{s.get('step_number')}. {s.get('description')}：{s.get('result')}"
        for s in steps
    ]
    if answer:
        lines.append(f"最终答案：{answer}")
    return "\n".join(lines)


async def narrate_solve_steps(
    caller: LLMCaller,
    *,
    kernel: str,
    task: str,
    answer: str,
    steps: list[dict],
) -> str:
    """内核真实 answer/steps -> 自然语言讲解（纯附加，不改写数值结果）。"""
    if not steps and not answer:
        return ""
    try:
        result = await caller(
            messages=[
                {
                    "role": "user",
                    "content": _render_steps(kernel, task, answer, steps),
                }
            ],
            system=_SYSTEM_PROMPT,
            max_tokens=800,
        )
        narration = str(result.get("content", "")).strip()
    except Exception:
        narration = ""

    if not narration:
        return _fallback_narration(steps, answer)
    return narration


__all__ = ["LLMCaller", "narrate_solve_steps"]
