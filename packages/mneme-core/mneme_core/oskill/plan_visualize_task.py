"""plan_visualize_task —— Visualize 模式题意理解层（W4 §3）。

给定学生/学习场景里的自然语言数学概念或数据描述，LLM 判断该用 4 种渲染
类型里的哪一种、以及需要哪些参数——不参与数值计算本身（svg_plot/three/
chart 三种类型的实际渲染数据完全交给 visualize_dispatch 调用真实内核
产出，VZ-4 红线；mermaid 是唯一例外，见下）。

组合 ≥2 oprim 形态：(1) 渲染类型注册表渲染成 prompt；(2) 注入的 LLM 调用 +
容错解析/校验（render_type 必须是 VISUALIZE_RENDER_TYPES 里真实存在的值，
不能编造；mermaid 类型额外校验 diagram_source 非空且不含明显的脚本注入
字样——防御性检查，mermaid.js 本身不执行任意 JS，但客户端渲染前多一层
校验不亏）。

FC-6：带"把学生概念映射到 Mneme 自己这 4 种渲染类型"的专属假设，留
mneme-core 私有。
"""

from __future__ import annotations

import json
from typing import Optional, Protocol

from mneme_core.oprim.models import VISUALIZE_RENDER_TYPES, VisualizeTaskPlan


class LLMCaller(Protocol):
    async def __call__(
        self,
        *,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 800,
    ) -> dict: ...


# 防御性检查：mermaid diagram_source 是 LLM 直接撰写的文本，客户端会拿去
# 交给 mermaid.js 解析渲染（不是 eval 任意 JS，但仍作为纵深防御的一层）。
_SUSPICIOUS_MERMAID_PATTERNS = (
    "<script",
    "javascript:",
    "onerror=",
    "onclick=",
    "onload=",
)


def _render_type_registry() -> str:
    lines = []
    for render_type, hint in VISUALIZE_RENDER_TYPES.items():
        lines.append(f"- {render_type}：{hint}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "你是中国中小学数学可视化助手。下面列出系统里唯一可用的渲染类型和"
    "各自需要的参数。给定一个数学概念/数据描述，判断应该用哪种渲染类型、"
    "以及需要哪些参数。只能从下面列出的渲染类型里选，不能编造列表之外的"
    "类型名字；数学表达式一律用 Python/SymPy 记法。只能输出严格 JSON：\n"
    '{"render_type":"","params":{},"restated_concept":""}\n'
    "restated_concept 用一句话复述你理解的可视化需求（供人核对你是否理解"
    "对了）。如果这个概念根本不适合用下面任何一种类型可视化，把 render_type"
    "留空字符串，不要编造一个凑合的类型/参数。\n\n"
    f"{_render_type_registry()}"
)


def _parse(raw: str) -> dict:
    """解析 LLM 输出为 dict——同 plan_solve_task._parse() 的两层兜底
    （剥离 markdown code fence → 提取 {...} 子串），真实 provider 不总是
    严格只输出裸 JSON。"""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            pass

    return {}


def _looks_suspicious(diagram_source: str) -> bool:
    lowered = diagram_source.lower()
    return any(p in lowered for p in _SUSPICIOUS_MERMAID_PATTERNS)


async def plan_visualize_task(
    caller: LLMCaller, *, concept_text: str
) -> VisualizeTaskPlan:
    """自然语言概念/数据描述 -> VisualizeTaskPlan（render_type/params，已校验）。

    LLM 调用失败/输出解析失败/render_type 不在真实注册表里 -> 返回带
    error 的 VisualizeTaskPlan，绝不返回一个"看起来能跑但文不对题"的猜测
    计划。
    """
    try:
        result = await caller(
            messages=[{"role": "user", "content": concept_text}],
            system=_SYSTEM_PROMPT,
            max_tokens=1200,
        )
        payload = _parse(result.get("content", ""))
    except Exception as exc:
        return VisualizeTaskPlan(error=f"可视化理解失败（LLM 调用异常：{exc}）")

    if not payload:
        return VisualizeTaskPlan(error="可视化理解失败（LLM 输出无法解析为 JSON）")

    render_type = str(payload.get("render_type", "")).strip()
    if render_type not in VISUALIZE_RENDER_TYPES:
        return VisualizeTaskPlan(error=f"未知渲染类型：{render_type!r}，不在支持列表内")

    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    if render_type == "mermaid":
        diagram_source = str(params.get("diagram_source", "")).strip()
        if not diagram_source:
            return VisualizeTaskPlan(error="mermaid 渲染类型缺少 diagram_source")
        if _looks_suspicious(diagram_source):
            return VisualizeTaskPlan(
                error="mermaid diagram_source 包含可疑内容，已拒绝"
            )

    return VisualizeTaskPlan(
        render_type=render_type,
        params=params,
        restated_concept=str(payload.get("restated_concept", "")).strip()[:400],
    )


__all__ = ["LLMCaller", "plan_visualize_task"]
