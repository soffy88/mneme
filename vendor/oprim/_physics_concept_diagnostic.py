"""oprim._physics_concept_diagnostic — FCI式概念诊断题生成（单次 LLM 调用）

给定误解库条目（label=误解陈述，remediation=重建方向），生成一道二选一情境诊断题：
一个选项体现该误解、另一个体现正确物理概念。哪个选项=误解在生成时即固定
（misconception_option），学生作答后判分是确定性查表，不再需要 LLM。

U.19：物理概念优先范式第一步（FCI式诊断），区别于答错后被动挂误解诊断——
这里是学习前主动探测，即便学生"蒙对"最终答案也能揭示其隐藏误解。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConceptDiagnosticResult:
    """一道 FCI 式概念诊断题。"""

    scenario: str
    option_a: str
    option_b: str
    misconception_option: str  # "A" | "B"（哪个选项体现误解，服务层不下发给客户端）


_SYSTEM = """你是高中物理教研员，正在编写 FCI（Force Concept Inventory）式概念诊断题。

给你一条学生常见误解（label）和正确重建方向（remediation），请编一道**情境化二选一**
诊断题：给出一个具体物理情境（scenario），A/B 两个选项分别代表"符合该误解的预测"和
"符合正确物理概念的预测"，让学生凭直觉选择自己真实认为会发生的结果——不是考记忆，
是测真实信念。

严格要求：
1. scenario 只描述情境和问题，不能暗示哪个选项对
2. A/B 选项都要像"有道理的预测"，不能有一个明显荒谬
3. 不出现"根据牛顿第X定律"这类提示性表述
4. 用高中生能理解的具体情境（不要抽象公式）

输出严格 JSON：
{"scenario": "...", "option_a": "...", "option_b": "...", "misconception_option": "A"}"""


async def generate_concept_diagnostic(
    *,
    misconception_label: str,
    remediation: str,
    ku_name: str,
    caller: Any,
    model: str = "claude-sonnet-4-6",
) -> ConceptDiagnosticResult:
    """生成一道二选一 FCI 式诊断题。

    Parameters
    ----------
    misconception_label : str
        误解陈述（来自 oprim.misconception.MISCONCEPTIONS）。
    remediation : str
        正确概念重建方向（同上）。
    ku_name : str
        当前知识点名（提供情境背景）。
    caller : Any
        LLM 调用者（注入）。
    model : str
        模型标识符。
    """
    import json

    from oprim.llm import llm_complete

    resp = await llm_complete(
        [
            {
                "role": "user",
                "content": (
                    f"知识点：{ku_name}\n"
                    f"常见误解：{misconception_label}\n"
                    f"正确重建方向：{remediation}"
                ),
            }
        ],
        caller=caller,
        system=_SYSTEM,
        model=model,
    )

    raw = resp.text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    scenario = (
        data.get("scenario") or f"关于「{ku_name}」，你认为下面哪种说法更符合实际？"
    )
    option_a = data.get("option_a") or misconception_label
    option_b = data.get("option_b") or remediation
    misconception_option = data.get("misconception_option")
    if misconception_option not in ("A", "B"):
        misconception_option = "A"

    return ConceptDiagnosticResult(
        scenario=scenario,
        option_a=option_a,
        option_b=option_b,
        misconception_option=misconception_option,
    )


__all__ = ["ConceptDiagnosticResult", "generate_concept_diagnostic"]
