"""Analyze a learner profile to extract strengths, weaknesses, and recommendations.

Async, single LLM call.

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProfilerInput:
    """Input for learner profile analysis.

    Attributes
    ----------
    kc_mastery : dict[str, float]
        Knowledge component mastery levels (kc_id -> 0..1).
    recent_attempts : list[dict]
        Recent attempt records (question_id, correct, kc_id, response_time_s).
    grade_level : str
        Student grade level.
    subject : str
        Subject area.
    target_goal : str | None
        Optional learning goal (e.g., "pass the college entrance exam").
    system : str | None
        Optional system prompt override.
    """

    kc_mastery: dict[str, float]
    recent_attempts: list[dict] = field(default_factory=list)
    grade_level: str = "中学"
    subject: str = "math"
    target_goal: str | None = None
    system: str | None = None


@dataclass(frozen=True)
class ProfilerResult:
    """Learner profile analysis result.

    Attributes
    ----------
    strengths : list[str]
        Strong knowledge areas.
    weaknesses : list[str]
        Weak knowledge areas needing attention.
    recommendations : list[str]
        Recommended practice focus areas.
    overall_level : str
        Overall assessment ("beginner"/"intermediate"/"advanced").
    mastery_summary : str
        Brief prose summary.
    success : bool
    error : str
    """

    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    overall_level: str = "unknown"
    mastery_summary: str = ""
    success: bool = True
    error: str = ""


_PROFILER_SYSTEM = (
    "You are an educational data analyst. Given a learner's knowledge mastery levels "
    "and recent attempt history, identify their strengths, weaknesses, and provide "
    "targeted recommendations. Respond with JSON: "
    '{"strengths": [...], "weaknesses": [...], "recommendations": [...], '
    '"overall_level": "beginner|intermediate|advanced", "mastery_summary": str}.'
)


async def profiler_analyze(
    inp: ProfilerInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> ProfilerResult:
    """Analyze a learner profile using an LLM.

    Parameters
    ----------
    inp : ProfilerInput
    caller : Any
    model : str
    max_tokens : int

    Returns
    -------
    ProfilerResult
    """
    from oprim.llm._llm_complete import llm_complete

    mastery_str = "\n".join(
        f"  {kc}: {v:.1%}" for kc, v in sorted(inp.kc_mastery.items())
    )
    recent_str = json.dumps(inp.recent_attempts[-20:], ensure_ascii=False) if inp.recent_attempts else "[]"

    prompt = (
        f"学生年级: {inp.grade_level}, 科目: {inp.subject}\n"
        f"学习目标: {inp.target_goal or '未指定'}\n"
        f"知识点掌握情况:\n{mastery_str}\n"
        f"最近 {len(inp.recent_attempts)} 次答题记录: {recent_str}\n"
        "请分析该学生的学习状态，返回 JSON。"
    )
    messages = [{"role": "user", "content": prompt}]
    system = inp.system or _PROFILER_SYSTEM

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")

        data = json.loads(raw)
        return ProfilerResult(
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            recommendations=data.get("recommendations", []),
            overall_level=data.get("overall_level", "unknown"),
            mastery_summary=data.get("mastery_summary", ""),
            success=True,
        )

    except Exception as exc:
        return ProfilerResult(success=False, error=str(exc))
