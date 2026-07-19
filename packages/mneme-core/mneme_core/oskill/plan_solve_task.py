"""plan_solve_task —— Solve 模式题意理解层（W4 §2）。

给定学生输入的自然语言数学题目，LLM 判断该用 7 个确定性内核里的哪一个、
哪个 task、以及需要哪些结构化参数——不参与求解本身（求解完全交给
vendor/oskill.solve_dispatch 调用的真实内核，本元素只做"选哪个内核+怎么调"
这一步的题意理解，SV-2/SV-4 红线要求求解步骤必须来自内核真实输出）。

组合 ≥2 oprim 形态：(1) 内核/任务注册表渲染成 prompt；(2) 注入的 LLM 调用 +
容错解析/校验（kernel 必须是 SOLVE_KERNEL_TASKS 里真实存在的内核、task
必须是该内核真实支持的任务——防止 LLM 编造不存在的内核/任务，解析失败或
校验不过时返回带 error 的 SolveTaskPlan，不猜测/不硬凑一个可能文不对题的
内核，同 book_spine._coerce_chapters() 的"不存在就丢弃/不采信"处置原则）。

FC-6：带"把学生题目映射到 Mneme 自己这 7 个内核"的专属假设，留 mneme-core
私有。

命名说明：刻意不叫 understand_problem——vendor/oprim/understand_problem.py
已经是一个不同用途的既有元素（Deep Solve 模式用于"识别题型+所需知识点"，
产出面向 RAG 方法检索的 problem_type/required_kus，不产出可调用的
内核/task/参数），两者互不相关，避免同名不同义造成混淆。
"""

from __future__ import annotations

import json
from typing import Optional, Protocol

from mneme_core.oprim.models import (
    SOLVE_KERNEL_PARAM_HINTS,
    SOLVE_KERNEL_TASKS,
    SolveTaskPlan,
)


class LLMCaller(Protocol):
    """注入式异步 LLM 调用契约，返回 {"content": <原始补全文本>}。

    真 provider 绑定在服务层完成（同 services/textbook_qa_service.py
    的 _get_caller() 模式），本元素不感知具体 provider。
    """

    async def __call__(
        self,
        *,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 800,
    ) -> dict: ...


def _render_kernel_registry() -> str:
    lines = []
    for kernel, tasks in SOLVE_KERNEL_TASKS.items():
        task_str = "、".join(tasks) if tasks else "（无 task 参数）"
        hint = SOLVE_KERNEL_PARAM_HINTS.get(kernel, "")
        lines.append(f"- {kernel}：task 可选 {task_str}；参数：{hint}")
    return "\n".join(lines)


_SYSTEM_PROMPT = (
    "你是中国中小学数学题目分类器。下面列出系统里唯一可用的确定性求解内核、"
    "它们各自支持的 task、以及需要的参数。给定一道学生题目，判断应该用哪个"
    "内核、哪个 task、以及从题目里提取出哪些参数值。只能从下面列出的内核和"
    "task 里选，不能编造列表之外的内核或 task 名字；数学表达式一律用 Python/"
    "SymPy 记法（乘方用 ** 或 ^ 均可，会自动归一化）。只能输出严格 JSON：\n"
    '{"kernel":"","task":"","params":{},"restated_problem":""}\n'
    "restated_problem 用一句话复述你理解的题目（供人核对你是否理解对了）。\n\n"
    "重要：如果题目根本不是数学题、或不属于下面任何一个内核能处理的范围，"
    "把 kernel 留空字符串，不要为了凑出一个看起来合法的 JSON 而编造一个"
    "无意义的占位内核/参数（比如硬凑一个 expression 等于 0 之类的假题目）——"
    "留空会被系统正确识别为「无法求解」并诚实告知学生，编造假内核反而会给出"
    "一个文不对题、误导学生的错误答案。\n\n"
    f"{_render_kernel_registry()}"
)


def _parse(raw: str) -> dict:
    """解析 LLM 输出为 dict——真实 provider 不总是严格只输出裸 JSON（偶尔会
    包一层 markdown code fence，或在 JSON 前后加解释性文字），单纯
    ``json.loads(raw)`` 在真实 provider 上实测会偶发失败（本地 fake caller
    测试不会暴露，因为测试脚本自己保证输出干净）。这里做两层兜底：先剥离
    code fence，再退化成"提取第一个 {...} 子串"重试一次。两次都失败才真正
    判定为解析失败。
    """
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


async def plan_solve_task(caller: LLMCaller, *, problem_text: str) -> SolveTaskPlan:
    """自然语言题目 -> SolveTaskPlan（kernel/task/params，已校验）。

    LLM 调用失败/输出解析失败/kernel 或 task 不在真实注册表里 -> 返回带
    error 的 SolveTaskPlan，绝不返回一个"看起来能跑但文不对题"的猜测计划。
    """
    try:
        result = await caller(
            messages=[{"role": "user", "content": problem_text}],
            system=_SYSTEM_PROMPT,
            max_tokens=500,
        )
        payload = _parse(result.get("content", ""))
    except Exception as exc:
        return SolveTaskPlan(error=f"题意理解失败（LLM 调用异常：{exc}）")

    if not payload:
        return SolveTaskPlan(error="题意理解失败（LLM 输出无法解析为 JSON）")

    kernel = str(payload.get("kernel", "")).strip()
    if kernel not in SOLVE_KERNEL_TASKS:
        return SolveTaskPlan(error=f"未知内核：{kernel!r}，不在支持列表内")

    valid_tasks = SOLVE_KERNEL_TASKS[kernel]
    task = str(payload.get("task", "")).strip()
    if valid_tasks and task not in valid_tasks:
        return SolveTaskPlan(error=f"内核 {kernel!r} 不支持 task {task!r}")

    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    return SolveTaskPlan(
        kernel=kernel,
        task=task,
        params=params,
        restated_problem=str(payload.get("restated_problem", "")).strip()[:400],
    )


__all__ = ["LLMCaller", "plan_solve_task"]
