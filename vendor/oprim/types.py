"""Shared type definitions for oprim — Mneme elements (M-A/M-B batch).

Version: oprim v3.4.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Mneme types — SolveResult / SolveStep / StepCheckResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SolveStep:
    """A single step in a math solution."""

    step_number: int
    description: str
    expression: str
    result: str
    is_correct: bool = True
    feedback: str = ""


@dataclass(frozen=True)
class StepCheckResult:
    """Result of checking a single solution step."""

    step_number: int
    is_correct: bool
    error_type: str = ""
    error_detail: str = ""
    suggestion: str = ""


@dataclass
class SolveResult:
    """Full result of a math problem solve attempt.

    Attributes:
        solvable: Whether the problem was successfully solved.
        answer: The final answer (string representation).
        steps: Ordered list of solution steps.
        step_checks: Validation results for each step (empty if not checked).
        method: Which method produced the result ("kernel", "llm", "hybrid").
        raw_expression: The original expression/equation.
        solution_latex: LaTeX rendering of the solution.
        confidence: Solver confidence 0..1.
        error: Error message if solve failed.
    """

    solvable: bool
    answer: str
    steps: list[SolveStep] = field(default_factory=list)
    step_checks: list[StepCheckResult] = field(default_factory=list)
    method: str = "kernel"
    raw_expression: str = ""
    solution_latex: str = ""
    confidence: float = 1.0
    error: str = ""


# ---------------------------------------------------------------------------
# Mneme types — Plot2DData / Three3DData (diagram generation)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Plot2DData:
    """Data for generating a 2D plot/diagram.

    Attributes:
        title: Plot title.
        x_label: X-axis label.
        y_label: Y-axis label.
        x_values: X data points.
        y_values: Y data points.
        annotations: List of (x, y, text) annotations.
        functions: Dict of label -> expression string for function curves.
        x_range: (min, max) for x-axis.
        y_range: (min, max) for y-axis.
    """

    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    x_values: list[float] = field(default_factory=list)
    y_values: list[float] = field(default_factory=list)
    annotations: list[tuple[float, float, str]] = field(default_factory=list)
    functions: dict[str, str] = field(default_factory=dict)
    x_range: tuple[float, float] = (-10.0, 10.0)
    y_range: tuple[float, float] = (-10.0, 10.0)


@dataclass(frozen=True)
class Three3DData:
    """Data for generating a 3D plot/diagram.

    Attributes:
        title: Plot title.
        x_label: X-axis label.
        y_label: Y-axis label.
        z_label: Z-axis label.
        x_values: X data points.
        y_values: Y data points.
        z_values: Z data points.
        surface_func: Expression string for surface z = f(x, y).
        x_range: (min, max) for x-axis.
        y_range: (min, max) for y-axis.
        z_range: (min, max) for z-axis.
    """

    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    z_label: str = "z"
    x_values: list[float] = field(default_factory=list)
    y_values: list[float] = field(default_factory=list)
    z_values: list[float] = field(default_factory=list)
    surface_func: str = ""
    x_range: tuple[float, float] = (-10.0, 10.0)
    y_range: tuple[float, float] = (-10.0, 10.0)
    z_range: tuple[float, float] = (-10.0, 10.0)


# ---------------------------------------------------------------------------
# Grade result (used by compute_feedback)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GradeResult:
    """Result of grading a student answer."""

    is_correct: bool
    method: str  # "kernel" | "llm"
    score: float = 0.0  # 0..1
    reason: str | None = None  # 批改原因说明（M-F compute_feedback）
    feedback: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Peer percentile data (used by compute_peer_percentile)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PeerPercentileResult:
    """Result of computing peer percentile ranking."""

    student_value: float
    percentile: float  # 0..100
    peer_count: int
    peer_mean: float
    peer_std: float
    distribution_bucket: str = ""  # e.g., "top_10%", "bottom_25%"


# ---------------------------------------------------------------------------
# Socratic dialogue (used by M-B/M-C elements)
# ---------------------------------------------------------------------------

class SocraticTurnResult(BaseModel):
    """Result of a single Socratic dialogue turn."""

    text: str
    step_check_triggered: bool = False

# ---------------------------------------------------------------------------
# KCState — defined in _cognitive.py, re-exported here for compatibility
# ---------------------------------------------------------------------------
from oprim._cognitive import KCState
