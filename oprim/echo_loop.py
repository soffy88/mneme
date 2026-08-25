"""
Echo-Loop 学习闭环原语实现（oprim 层）
=========================================

复刻自 Echo-Loop App 的核心学习方法论：
  盲听 → 精听 → 跟读 → 复述 → 科学间隔复习 → 通关

每个函数都是单次原子操作，遵循 3O 范式 oprim 约束：
- 互不调用
- 纯函数倾向
- 输入输出通过 Pydantic 模型定义

依赖：
- vendor.oprim.fsrs_engine（间隔复习调度）
- vendor.oprim.bkt（掌握度更新）
- vendor.oprim.cognitive（统一认知更新）
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

# ──────────────────────────────────────────────────────────────────────────────
# T.1 盲听 (Blind Listen) — 完整听一遍，感知整体难度
# ──────────────────────────────────────────────────────────────────────────────

class BlindListenInput(BaseModel):
    """盲听阶段输入。"""
    audio_url: str = ""
    audio_b64: str = ""
    transcript: str = ""  # 原始文本
    reference_kc_ids: list[str] = Field(default_factory=list)  # 关联知识点
    language: str = "en"
    model_config = ConfigDict(arbitrary_types_allowed=True)


class BlindListenOutput(BaseModel):
    """盲听阶段输出 — 感知难度打分。"""
    perceived_difficulty: float = Field(ge=0.0, le=1.0)  # 0-1，1=最难
    detected_kcs: list[str] = Field(default_factory=list)  # 检测到的KC
    key_phrases: list[str] = Field(default_factory=list)  # 关键短语
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
    """
    盲听 Stage 1: 完整播放一遍音频，感知整体难度。

    通过语汇复杂度、句长分布等指标评估难度。

    输入:
        audio_b64: 音频 base64 数据
        audio_url: 音频 URL
        transcript: 原始文本（如有）
        reference_kc_ids: 参考知识点ID列表
        language: 语言代码

    输出:
        perceived_difficulty: 感知难度 (0-1)
        detected_kcs: 检测到的知识点
        key_phrases: 关键短语
        estimated_duration_s: 估计时长
    """
    if not audio_b64 and not audio_url:
        return BlindListenOutput(
            perceived_difficulty=0.5,
            note="No audio provided"
        )

    text = transcript or ""
    word_count = len(text.split())
    avg_word_length = sum(len(w) for w in text.split()) / max(word_count, 1)

    difficulty = min(1.0, max(0.0, (avg_word_length / 10.0) + (word_count / 1000.0)))

    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    key_phrases = sorted(sentences, key=len, reverse=True)[:3]

    detected_kcs = reference_kc_ids or []

    return BlindListenOutput(
        perceived_difficulty=round(difficulty, 4),
        detected_kcs=detected_kcs,
        key_phrases=key_phrases,
        estimated_duration_s=len(text) * 0.3,
        note=f"Estimated from {word_count} words",
    )


# ──────────────────────────────────────────────────────────────────────────────
# T.2 精听 (Intensive Listen) — 逐句听懂，标记重点难句
# ──────────────────────────────────────────────────────────────────────────────

class IntensiveListenInput(BaseModel):
    """精听阶段输入。"""
    transcript: str  # 完整文本
    blind_listen_output: Optional[dict] = None  # 前一步结果
    language: str = "en"


class IntensiveListenOutput(BaseModel):
    """精听阶段输出 — 逐句解析。"""
    sentences: list[dict] = Field(default_factory=list)  # 按句解析结果
    difficult_sentences: list[dict] = Field(default_factory=list)  # 标记难句
    intent_labels: list[str] = Field(default_factory=list)  # 意图标签
    total_sentences: int = 0


async def intensive_listen_parse(
    *,
    transcript: str,
    blind_listen_output: Optional[dict] = None,
    language: str = "en",
) -> IntensiveListenOutput:
    """
    精听 Stage 2: 逐句听懂，标记重点难句。

    将文本分割成句子，评估每个句子的难度，标记难句。

    输入:
        transcript: 完整文本
        blind_listen_output: 前一步盲听结果
        language: 语言代码

    输出:
        sentences: 按句解析结果（文本、难度、词汇量）
        difficult_sentences: 标记难句
        intent_labels: 意图标签
    """
    if not transcript:
        return IntensiveListenOutput(sentences=[], difficult_sentences=[])

    raw_sentences = re.split(r'(?<=[.!?])\s+', transcript.strip())
    sentences_data = []
    difficult_sentences = []

    overall_difficulty = 0.5
    if blind_listen_output and isinstance(blind_listen_output.get("perceived_difficulty"), (int, float)):
        overall_difficulty = blind_listen_output["perceived_difficulty"]

    for idx, sentence in enumerate(raw_sentences):
        sentence_clean = sentence.strip()
        if not sentence_clean:
            continue

        word_count = len(sentence_clean.split())
        avg_word_len = sum(len(w) for w in sentence_clean.split()) / max(word_count, 1) if word_count > 0 else 0
        sent_difficulty = min(1.0, max(0.0, 0.3 * (word_count / 15) + 0.7 * (avg_word_len / 8)))

        is_difficult = sent_difficulty > (0.4 + overall_difficulty * 0.3)

        sent_data = {
            "index": idx,
            "text": sentence_clean,
            "word_count": word_count,
            "difficulty": round(sent_difficulty, 4),
            "is_marked_difficult": is_difficult,
            "intent": _classify_sentence_intent(sentence_clean),
        }
        sentences_data.append(sent_data)

        if is_difficult:
            difficult_sentences.append({
                "index": idx,
                "text": sentence_clean,
                "difficulty": round(sent_difficulty, 4),
                "reason": "high_complexity" if word_count > 20 else "rare_words",
            })

    intent_labels = list(dict.fromkeys(s["intent"] for s in sentences_data))

    return IntensiveListenOutput(
        sentences=sentences_data,
        difficult_sentences=difficult_sentences,
        intent_labels=intent_labels,
        total_sentences=len(sentences_data),
    )


def _classify_sentence_intent(text: str) -> str:
    """简单意图分类。"""
    text_lower = text.lower()
    if any(w in text_lower for w in ["but", "however", "although"]):
        return "contrast"
    if any(
        re.search(rf"\b{word}\b", text_lower)
        for word in ["what", "how", "why", "when", "where", "who"]
    ):
        return "question"
    if any(w in text_lower for w in ["because", "since", "as", "due to"]):
        return "explanation"
    if any(w in text_lower for w in ["first", "then", "next", "finally", "last"]):
        return "sequence"
    return "statement"


# ──────────────────────────────────────────────────────────────────────────────
# T.3 跟读 (Shadowing) — 模仿语音语调，训练发音能力
# ──────────────────────────────────────────────────────────────────────────────

class ShadowingInput(BaseModel):
    """跟读阶段输入。"""
    reference_text: str  # 原文
    student_audio_b64: str  # 学生录音
    pronunciation_scores: Optional[dict] = None  # 发音分数 (如有)


class ShadowingOutput(BaseModel):
    """跟读阶段输出 — 评估结果。"""
    overall_score: float = Field(ge=0.0, le=1.0)  # 总分
    fluency_match: float = Field(ge=0.0, le=1.0)  # 流畅度匹配
    intonation_match: float = Field(ge=0.0, le=1.0)  # 语调匹配
    pronunciation_match: float = Field(ge=0.0, le=1.0)  # 发音准确度
    missed_words: list[str] = Field(default_factory=list)  # 未命中单词
    suggestions: list[str] = Field(default_factory=list)  # 改进建议
    is_passing: bool = False  # 是否达标


async def shadowing_evaluate(
    *,
    reference_text: str,
    student_audio_b64: str,
    pronunciation_scores: Optional[dict] = None,
) -> ShadowingOutput:
    """
    跟读 Stage 3: 模仿语音语调，训练发音能力。

    对比学生录音与原文，评估流畅度、语调、发音准确度。

    输入:
        reference_text: 原文参考文本
        student_audio_b64: 学生录音（base64）
        pronunciation_scores: 外部发音评测结果（如有）

    输出:
        overall_score: 总体评分 (0-1)
        fluency_match: 流畅度匹配度
        intonation_match: 语调匹配度
        pronunciation_match: 发音准确度
        missed_words: 未命中单词
        suggestions: 改进建议
        is_passing: 是否达标
    """
    if pronunciation_scores:
        overall = (
            pronunciation_scores.get("overall", 0.5) * 0.4 +
            pronunciation_scores.get("fluency", 0.5) * 0.3 +
            pronunciation_scores.get("accuracy", 0.5) * 0.3
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

    ref_words = set(reference_text.lower().split())
    match_rate = len(ref_words & set(reference_text.lower().split())) / max(len(ref_words), 1)

    return ShadowingOutput(
        overall_score=round(match_rate, 4),
        fluency_match=round(min(1.0, match_rate), 4),
        intonation_match=round(max(0.1, match_rate - 0.1), 4),
        pronunciation_match=round(max(0.2, match_rate - 0.05), 4),
        missed_words=[],
        suggestions=["Practice rhythm and stress patterns"] if match_rate < 0.8 else [],
        is_passing=match_rate >= 0.6,
    )


# ──────────────────────────────────────────────────────────────────────────────
# T.4 复述 (Retell) — 用自己的话表达，提升输出能力
# ──────────────────────────────────────────────────────────────────────────────

class RetellInput(BaseModel):
    """复述阶段输入。"""
    original_text: str  # 原文
    student_retell: str  # 学生复述内容
    reference_kc_ids: list[str] = Field(default_factory=list)


class RetellOutput(BaseModel):
    """复述阶段输出 — 评估结果。"""
    coverage_score: float = Field(ge=0.0, le=1.0)  # 内容覆盖度
    accuracy_score: float = Field(ge=0.0, le=1.0)  # 内容准确度
    fluency_score: float = Field(ge=0.0, le=1.0)  # 流畅度
    missing_key_points: list[str] = Field(default_factory=list)  # 遗漏要点
    hallucinated_points: list[str] = Field(default_factory=list)  # 错误要点
    overall_score: float = Field(ge=0.0, le=1.0)  # 总分
    is_passing: bool = False  # 是否达标


async def retell_evaluate(
    *,
    original_text: str,
    student_retell: str,
    reference_kc_ids: Optional[list[str]] = None,
) -> RetellOutput:
    """
    复述 Stage 4: 用自己的话表达，提升输出能力。

    评估学生复述内容与原文的覆盖度、准确度、流畅度。

    输入:
        original_text: 原文
        student_retell: 学生复述内容
        reference_kc_ids: 关联知识点ID

    输出:
        coverage_score: 内容覆盖度 (0-1)
        accuracy_score: 内容准确度 (0-1)
        fluency_score: 流畅度 (0-1)
        missing_key_points: 遗漏要点
        hallucinated_points: 错误要点
        overall_score: 总体评分 (0-1)
        is_passing: 是否达标
    """
    ref_words = set(original_text.lower().split())
    stu_words = set(student_retell.lower().split())

    if not ref_words:
        return RetellOutput(
            coverage_score=1.0,
            accuracy_score=1.0,
            fluency_score=1.0,
            overall_score=1.0,
            is_passing=True,
        )

    covered = len(ref_words & stu_words)
    coverage_score = covered / len(ref_words) if ref_words else 1.0

    accurate = len(ref_words & stu_words)
    accuracy_score = accurate / len(stu_words) if stu_words else 0.0

    stu_word_count = len(stu_words)
    stu_avg_word_len = sum(len(w) for w in stu_words) / max(stu_word_count, 1) if stu_word_count else 0
    fluency_score = max(0.0, min(1.0, 0.5 + (stu_avg_word_len - 3) / 10))

    missing = list(ref_words - stu_words)[:5]
    hallucinated = list(stu_words - ref_words)[:5]

    overall = (coverage_score * 0.4 + accuracy_score * 0.4 + fluency_score * 0.2)

    return RetellOutput(
        coverage_score=round(coverage_score, 4),
        accuracy_score=round(accuracy_score, 4),
        fluency_score=round(fluency_score, 4),
        missing_key_points=missing,
        hallucinated_points=hallucinated,
        overall_score=round(overall, 4),
        is_passing=overall >= 0.6,
    )
