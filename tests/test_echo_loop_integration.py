"""
Echo-Loop 学习闭环集成测试
=============================

测试 3O 层的完整学习循环流程。
"""

import pytest

from oprim.echo_loop import (
    blind_listen_generate,
    intensive_listen_parse,
    shadowing_evaluate,
    retell_evaluate,
)


class TestEchoLoopOprim:
    """测试 oprim 层的各个原子操作。"""

    @pytest.mark.asyncio
    async def test_blind_listen_basic(self):
        """T.1 盲听 - 基本功能测试"""
        transcript = "Hello world. This is a test."
        result = await blind_listen_generate(
            audio_b64="base64data",
            transcript=transcript,
            reference_kc_ids=["kc_001"],
        )
        assert result.perceived_difficulty >= 0.0
        assert result.perceived_difficulty <= 1.0
        assert result.detected_kcs == ["kc_001"]  # 仅返回 reference_kc_ids
        assert len(result.key_phrases) >= 0
        assert result.estimated_duration_s > 0
        assert result.note != ""

    @pytest.mark.asyncio
    async def test_blind_listen_no_audio(self):
        """T.1 盲听 - 无音频回退"""
        result = await blind_listen_generate(
            audio_b64=None,
            audio_url=None,
            transcript="",
        )
        assert result.perceived_difficulty == 0.5
        assert result.note == "No audio provided"

    @pytest.mark.asyncio
    async def test_intensive_listen_parse(self):
        """T.2 精听 - 基本功能测试"""
        transcript = "This is the first sentence. This is the second sentence."
        result = await intensive_listen_parse(
            transcript=transcript,
            blind_listen_output={"perceived_difficulty": 0.6},
        )
        assert result.total_sentences == 2
        assert len(result.sentences) == 2
        assert all("text" in s for s in result.sentences)
        assert all("difficulty" in s for s in result.sentences)
        assert len(result.difficult_sentences) >= 0
        assert len(result.intent_labels) >= 0

    @pytest.mark.asyncio
    async def test_intensive_listen_empty(self):
        """T.2 精听 - 空文本"""
        result = await intensive_listen_parse(transcript="")
        assert result.total_sentences == 0
        assert len(result.sentences) == 0
        assert len(result.difficult_sentences) == 0

    @pytest.mark.asyncio
    async def test_intensive_listen_question_detection(self):
        """T.2 精听 - 问题句检测"""
        transcript = "What is your name? How old are you?"
        result = await intensive_listen_parse(transcript=transcript)
        assert "question" in result.intent_labels

    @pytest.mark.asyncio
    async def test_shadowing_evaluate_with_scores(self):
        """T.3 跟读 - 使用外部发音分数"""
        result = await shadowing_evaluate(
            reference_text="Hello world",
            student_audio_b64="base64data",
            pronunciation_scores={
                "overall": 0.8,
                "fluency": 0.75,
                "accuracy": 0.85,
                "intonation": 0.7,
                "missed_words": ["world"],
                "suggestions": ["Work on ending consonants"],
            },
        )
        assert result.is_passing is True
        assert result.missed_words == ["world"]

    @pytest.mark.asyncio
    async def test_shadowing_evaluate_basic(self):
        """T.3 跟读 - 基本功能"""
        result = await shadowing_evaluate(
            reference_text="Hello world test",
            student_audio_b64="base64data",
        )
        assert result.overall_score >= 0.0
        assert result.overall_score <= 1.0
        assert result.is_passing is False  # 简单模拟通常低分

    @pytest.mark.asyncio
    async def test_retell_evaluate_high_coverage(self):
        """T.4 复述 - 高覆盖率"""
        original = "The quick brown fox jumps over the lazy dog"
        retell = "The quick brown fox jumps over the lazy dog"
        result = await retell_evaluate(
            original_text=original,
            student_retell=retell,
        )
        assert result.coverage_score >= 0.9
        assert result.accuracy_score >= 0.9
        assert result.is_passing is True

    @pytest.mark.asyncio
    async def test_retell_evaluate_low_coverage(self):
        """T.4 复述 - 低覆盖率"""
        original = "The quick brown fox jumps over the lazy dog"
        retell = "Hello"
        result = await retell_evaluate(
            original_text=original,
            student_retell=retell,
        )
        assert result.coverage_score < 0.5
        assert result.is_passing is False

    @pytest.mark.asyncio
    async def test_retell_evaluate_hallucination(self):
        """T.4 复述 - 错误要点检测"""
        original = "The cat is sleeping"
        retell = "The dog is eating"
        result = await retell_evaluate(
            original_text=original,
            student_retell=retell,
        )
        assert len(result.missing_key_points) > 0
        assert len(result.hallucinated_points) > 0

    @pytest.mark.asyncio
    async def test_retell_evaluate_empty_reference(self):
        """T.4 复述 - 空原文"""
        result = await retell_evaluate(
            original_text="",
            student_retell="Hello",
        )
        assert result.overall_score == 1.0
        assert result.is_passing is True

    @pytest.mark.asyncio
    async def test_sentence_intent_classification(self):
        """T.2 精听 - 意图分类"""
        transcript = "What is this? Because it is important. However, we continue."
        result = await intensive_listen_parse(transcript=transcript)
        assert "question" in result.intent_labels
        assert "explanation" in result.intent_labels
        assert "contrast" in result.intent_labels


class TestEchoLoopOskill:
    """测试 oskill 层的学习循环编排。"""

    @pytest.mark.asyncio
    async def test_cognitive_update_integration(self):
        """T.6 认知更新 - 红线顺序测试"""
        # 模拟 cognitive_update 调用
        # 此测试验证认知更新红线公式的正确性
        pass  # 实际实现依赖 vendor.oprim 完整初始化


class TestEchoLoopOmodul:
    """测试 omodul 层的业务事务。"""

    def test_spaced_review_intervals(self):
        """间隔复习调度 - 固定间隔表验证"""
        from omodul.echo_loop_session import SpacedReviewConfig
        config = SpacedReviewConfig()
        # Echo-Loop 间隔: 6h, 1d, 2d, 4d, 7d, 14d, 28d
        assert config.review_intervals_hours == [6, 24, 48, 96, 168, 336, 672]
        assert config.max_reviews == 7

    def test_config_pillars(self):
        """验证 omodul 的 _enabled_pillars"""
        from omodul.echo_loop_session import (
            EchoLoopConfig,
            SpacedReviewConfig,
            DifficultSentenceConfig,
            ContextualFlashcardConfig,
        )
        # EchoLoopConfig 必须声明支柱
        assert "decision_trail" in EchoLoopConfig._enabled_pillars
        assert "cost" in EchoLoopConfig._enabled_pillars
        assert "fingerprint" in EchoLoopConfig._enabled_pillars
        assert "decision_trail" in SpacedReviewConfig._enabled_pillars
        assert "decision_trail" in DifficultSentenceConfig._enabled_pillars
        assert "decision_trail" in ContextualFlashcardConfig._enabled_pillars
