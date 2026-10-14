"""拍照问题目的确定性求解内核（不调用 LLM）。

包结构：
- core       结果类型 KernelSolution、题面规范化（全角/上下标/OCR 混淆）、数字格式化
- sym        数学式子抽取 + 沙箱解析（obase.sympy_runtime，AST 白名单 + fork 超时）
- arith      有理数/分数/小数/百分数、乘方、科学记数法、二次根式、特殊角三角函数
- algebra    一元方程（一次/二次/分式/绝对值/含参）、韦达、不等式（组）、方程组、整式分式
- functions  一次函数、二次函数、反比例函数
- geometry   勾股、解直角三角形、圆/扇形、平面图形、多边形角、三角形角、相似
- stats      统计量、概率、比例/百分率、单位换算
- word       应用题模板：行程、工程、利润折扣、浓度、年龄、鸡兔同笼
- physics    初中物理公式（带单位换算）
- chemistry  相对分子质量、质量分数、溶液、根据化学方程式计算
- router     分类 + 按置信度依次尝试 + 多题拆分
- variants   错题变式（扰动数字 → 重解 → 校验答案干净）与内核判分
- similar    没有精确内核时，从已解题库里找相似题

对外 API（photo_ask_service / wrongbook_review_service 使用）：
    solve_exact(text, subject) -> KernelSolution | None   （async，带超时）
    solve_text(text, subject)  -> KernelSolution | None   （同步）
    split_questions(text)      -> list[dict]
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from services.ask_kernels.core import KernelSolution, basic_normalize
from services.ask_kernels.balance import find_chemical_equation, solve_chemistry_text
from services.ask_kernels.router import classify, solve_text, split_questions
from services.ask_kernels.sym import math_normalize

def normalize_math_text(text: str) -> str:
    """兼容旧接口：OCR/手输题面 → 便于抠式子的形式。"""
    return math_normalize(text)


def solve_math_text(text: str) -> Optional[KernelSolution]:
    """兼容旧接口：只用数学内核（同步）。"""
    return solve_text(text, "math", families={"algebra", "arith", "function", "geometry", "stats", "word"})


async def solve_exact(text: str, subject: Optional[str]) -> Optional[KernelSolution]:
    """按题面路由到精确内核；都不适用返回 None（调用方再找相似题/回落）。"""
    timeout = float(os.environ.get("MNEME_ASK_KERNEL_TIMEOUT", "5"))
    sol: Optional[KernelSolution] = None
    try:
        # 线程里跑（CPU 轻、毫秒级）；外部输入的解析在 obase 沙箱子进程里（fork + 硬超时），
        # 内核自身对输入长度/次数/指数都设了上限，budget 用完就停止尝试后续内核。
        sol = await asyncio.wait_for(asyncio.to_thread(solve_text, text, subject, budget_s=timeout), timeout=timeout + 2.0)
    except Exception:  # noqa: BLE001 — 超时/异常 → 当作没解出来
        sol = None
    if (sol is None or not sol.kernel.startswith("chemistry")) and find_chemical_equation(text):
        chem = await solve_chemistry_text(text)
        if chem is not None and (sol is None or "配平" in basic_normalize(text)):
            return chem
    return sol


__all__ = [
    "KernelSolution",
    "classify",
    "find_chemical_equation",
    "normalize_math_text",
    "solve_exact",
    "solve_math_text",
    "solve_text",
    "split_questions",
]
