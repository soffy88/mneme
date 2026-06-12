"""Mneme oprim 层共享数据结构。由所有 oprim/oskill 导入，不依赖 obase/omodul担。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from pydantic import BaseModel


# ── BKT ──────────────────────────────────────────────────────────────────────
@dataclass
class KCState:
    """单个学生在单个知识点上的认知状态（BKT + 识别维度）。"""
    kc_id: str
    p_init: float = 0.20
    p_transit: float = 0.20
    p_guess: float = 0.15
    p_slip: float = 0.12
    p_mastery: Optional[float] = None       # None = 用先验 p_init
    long_term_mastery: Optional[float] = None
    last_interaction_ts: Optional[float] = None
    n_attempts: int = 0
    # 识别维度（M-G）
    p_recognition: Optional[float] = None
    p_recognition_init: float = 0.20

    def current(self) -> float:
        return self.p_mastery if self.p_mastery is not None else self.p_init

    def current_recognition(self) -> float:
        return self.p_recognition if self.p_recognition is not None \
               else self.p_recognition_init


# ── 求解内核 ──────────────────────────────────────────────────────────────────
class SolveStep(BaseModel):
    step_no: int
    latex: str                      # LaTeX 表达式
    value: Optional[str] = None     # 数值结果（若有）
    description: str = ""


class SolveResult(BaseModel):
    """所有 solve_* oprim 的统一返回类型。"""
    solvable: bool
    answer: str                     # LaTeX，不可解时为 ""
    steps: list[SolveStep] = []
    plot_data: Optional[dict] = None  # 供 kernel_to_plot2d/three 使用的源数据
    error: Optional[str] = None     # solvable=False 时的原因


class StepCheckResult(BaseModel):
    """verify_step 返回类型。"""
    valid: bool
    reason: Optional[str] = None    # invalid 时必填


# ── 图示数据 ──────────────────────────────────────────────────────────────────
class Plot2DData(BaseModel):
    """kernel_to_plot2d 返回：Mafs 可直接消费的数据格式。"""
    kc_type: str                    # "function" | "conic" | "trig" | "stat"
    traces: list[dict]              # [{type:"fn"|"point"|"segment", params:{}}]
    annotations: list[dict] = []   # [{type:"label", x, y, text}]
    x_range: tuple[float,float] = (-10.0, 10.0)
    y_range: tuple[float,float] = (-10.0, 10.0)


class Three3DData(BaseModel):
    """kernel_to_three 返回：Three.js 可直接消费的数据格式。"""
    vertices: list[list[float]]     # [[x,y,z], ...]
    edges: list[list[int]]          # [[i,j], ...] 索引对
    faces: list[list[int]] = []     # [[i,j,k], ...] 三角面
    labels: list[dict] = []         # [{text, position:[x,y,z]}]


# ── 变式题 ────────────────────────────────────────────────────────────────────
class VariantItem(BaseModel):
    """generate_variant 返回的单道变式题。"""
    kc_id: str
    question_latex: str
    answer: str                     # 由 solve_* 内核验证后填入
    solution_steps: list[SolveStep]
    plot_data: Optional[Plot2DData] = None
    kernel_verified: bool = False   # solve_* 验过答案后置 True
    difficulty: float = 0.5         # 0.0~1.0


# ── 苏格拉底 ──────────────────────────────────────────────────────────────────
class SocraticTurnResult(BaseModel):
    text: str                       # AI 输出的追问文字
    emotion_signal: Optional[str] = None  # "anxious"|"crisis"|"angry"|None
    step_verified: Optional[bool] = None  # 若本轮含 verify_step 结果
