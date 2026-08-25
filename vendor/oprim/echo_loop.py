"""Educational Echo-Loop primitives used by the runtime vendor closure.

The implementation is intentionally deterministic when no external speech
scores are supplied.  It reports uncertainty rather than treating the
reference text as a student's pronunciation result.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BlindListenInput(BaseModel):
    audio_url: str = ""
    audio_b64: str = ""
    transcript: str = ""
    reference_kc_ids: list[str] = Field(default_factory=list)
    language: str = "en"
    model_config = ConfigDict(arbitrary_types_allowed=True)


class BlindListenOutput(BaseModel):
    perceived_difficulty: float = Field(ge=0.0, le=1.0)
    detected_kcs: list[str] = Field(default_factory=list)
    key_phrases: list[str] = Field(default_factory=list)
    estimated_duration_s: int = 0
    note: str = ""


async def blind_listen_generate(
    *,
    audio_b64: Optional[str] = None,
    audio_url: Optional[str] = None,
    transcript: str = "",
    reference_kc_ids: Optional[list[str]] = None,
    language: str = "en",
) -> BlindListenOutput:
    if not audio_b64 and not audio_url:
        return BlindListenOutput(perceived_difficulty=0.5, note="No audio provided")
    words = transcript.split()
    average_word_length = sum(len(word) for word in words) / max(len(words), 1)
    difficulty = min(1.0, max(0.0, average_word_length / 10.0 + len(words) / 1000.0))
    sentences = [item.strip() for item in re.split(r"[.!?]+", transcript) if item.strip()]
    return BlindListenOutput(
        perceived_difficulty=round(difficulty, 4),
        detected_kcs=reference_kc_ids or [],
        key_phrases=sorted(sentences, key=len, reverse=True)[:3],
        estimated_duration_s=int(len(transcript) * 0.3),
        note=f"Estimated from {len(words)} words",
    )


class IntensiveListenInput(BaseModel):
    transcript: str
    blind_listen_output: Optional[dict] = None
    language: str = "en"


class IntensiveListenOutput(BaseModel):
    sentences: list[dict] = Field(default_factory=list)
    difficult_sentences: list[dict] = Field(default_factory=list)
    intent_labels: list[str] = Field(default_factory=list)
    total_sentences: int = 0


def _classify_sentence_intent(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("but", "however", "although")):
        return "contrast"
    if any(
        re.search(rf"\b{word}\b", lowered)
        for word in ("what", "how", "why", "when", "where", "who")
    ):
        return "question"
    if any(word in lowered for word in ("because", "since", "as", "due to")):
        return "explanation"
    if any(word in lowered for word in ("first", "then", "next", "finally", "last")):
        return "sequence"
    return "statement"


async def intensive_listen_parse(
    *,
    transcript: str,
    blind_listen_output: Optional[dict] = None,
    language: str = "en",
) -> IntensiveListenOutput:
    if not transcript:
        return IntensiveListenOutput()
    raw_sentences = re.split(r"(?<=[.!?])\s+", transcript.strip())
    overall_difficulty = 0.5
    if blind_listen_output and isinstance(
        blind_listen_output.get("perceived_difficulty"), (int, float)
    ):
        overall_difficulty = float(blind_listen_output["perceived_difficulty"])
    sentences: list[dict] = []
    difficult: list[dict] = []
    for index, sentence in enumerate(raw_sentences):
        text = sentence.strip()
        if not text:
            continue
        words = text.split()
        average_word_length = sum(len(word) for word in words) / max(len(words), 1)
        difficulty = min(1.0, max(0.0, 0.3 * len(words) / 15 + 0.7 * average_word_length / 8))
        item = {
            "index": index,
            "text": text,
            "word_count": len(words),
            "difficulty": round(difficulty, 4),
            "is_marked_difficult": difficulty > 0.4 + overall_difficulty * 0.3,
            "intent": _classify_sentence_intent(text),
        }
        sentences.append(item)
        if item["is_marked_difficult"]:
            difficult.append(
                {
                    "index": index,
                    "text": text,
                    "difficulty": round(difficulty, 4),
                    "reason": "high_complexity" if len(words) > 20 else "rare_words",
                }
            )
    return IntensiveListenOutput(
        sentences=sentences,
        difficult_sentences=difficult,
        intent_labels=list(dict.fromkeys(item["intent"] for item in sentences)),
        total_sentences=len(sentences),
    )


class ShadowingInput(BaseModel):
    reference_text: str
    student_audio_b64: str
    pronunciation_scores: Optional[dict] = None


class ShadowingOutput(BaseModel):
    overall_score: float = Field(ge=0.0, le=1.0)
    fluency_match: float = Field(ge=0.0, le=1.0)
    intonation_match: float = Field(ge=0.0, le=1.0)
    pronunciation_match: float = Field(ge=0.0, le=1.0)
    missed_words: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    is_passing: bool = False


async def shadowing_evaluate(
    *,
    reference_text: str,
    student_audio_b64: str,
    pronunciation_scores: Optional[dict] = None,
) -> ShadowingOutput:
    if pronunciation_scores:
        overall = (
            pronunciation_scores.get("overall", 0.5) * 0.4
            + pronunciation_scores.get("fluency", 0.5) * 0.3
            + pronunciation_scores.get("accuracy", 0.5) * 0.3
        )
        return ShadowingOutput(
            overall_score=round(overall, 4),
            fluency_match=round(pronunciation_scores.get("fluency", 0.5), 4),
            intonation_match=round(pronunciation_scores.get("intonation", 0.5), 4),
            pronunciation_match=round(pronunciation_scores.get("accuracy", 0.5), 4),
            missed_words=pronunciation_scores.get("missed_words", []),
            suggestions=pronunciation_scores.get("suggestions", []),
            is_passing=overall >= 0.6,
        )
    return ShadowingOutput(
        overall_score=0.5,
        fluency_match=0.5,
        intonation_match=0.4,
        pronunciation_match=0.45,
        suggestions=["Provide pronunciation scores for a verified result"],
        is_passing=False,
    )


class RetellInput(BaseModel):
    original_text: str
    student_retell: str
    reference_kc_ids: list[str] = Field(default_factory=list)


class RetellOutput(BaseModel):
    coverage_score: float = Field(ge=0.0, le=1.0)
    accuracy_score: float = Field(ge=0.0, le=1.0)
    fluency_score: float = Field(ge=0.0, le=1.0)
    missing_key_points: list[str] = Field(default_factory=list)
    hallucinated_points: list[str] = Field(default_factory=list)
    overall_score: float = Field(ge=0.0, le=1.0)
    is_passing: bool = False


async def retell_evaluate(
    *,
    original_text: str,
    student_retell: str,
    reference_kc_ids: Optional[list[str]] = None,
) -> RetellOutput:
    reference = set(original_text.lower().split())
    retell = set(student_retell.lower().split())
    if not reference:
        return RetellOutput(
            coverage_score=1.0,
            accuracy_score=1.0,
            fluency_score=1.0,
            overall_score=1.0,
            is_passing=True,
        )
    coverage = len(reference & retell) / len(reference)
    accuracy = len(reference & retell) / max(len(retell), 1)
    average_word_length = sum(len(word) for word in retell) / max(len(retell), 1)
    fluency = max(0.0, min(1.0, 0.5 + (average_word_length - 3) / 10))
    overall = coverage * 0.4 + accuracy * 0.4 + fluency * 0.2
    return RetellOutput(
        coverage_score=round(coverage, 4),
        accuracy_score=round(accuracy, 4),
        fluency_score=round(fluency, 4),
        missing_key_points=list(reference - retell)[:5],
        hallucinated_points=list(retell - reference)[:5],
        overall_score=round(overall, 4),
        is_passing=overall >= 0.6,
    )
