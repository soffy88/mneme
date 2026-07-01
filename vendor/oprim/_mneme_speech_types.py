"""Shared types for Mneme speech & essay batch functions.

All concrete types are dataclasses so oprim stays pydantic-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PronunciationResult:
    overall_score: float
    fluency_score: float
    accuracy_score: float
    word_scores: list[dict]  # [{word: str, score: float, issue: str}]


@dataclass
class SpeakingPracticeResult:
    turns: list[dict]                          # per-turn interaction records
    pronunciation_scores: list[PronunciationResult]
    overall_progress: float                    # mean overall_score across turns


@dataclass
class EssayAssessmentResult:
    rubric_scores: dict[str, float]            # {dimension: 0–100}
    guidance_questions: list[str]              # each ends with "？"
    revision_needed: bool


@dataclass
class EssayAssessmentInput:
    essay_text: str
    grade_level: str = "高中"
    essay_type: str = "议论文"
    user_id: str = ""
