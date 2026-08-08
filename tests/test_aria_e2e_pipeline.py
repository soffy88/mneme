"""Aria E2E Pipeline Integration — 全链路降级测试。

验证 3D VRM 管线：
  Director → perception → TTS → EchoDrive → 降级

不依赖真 GPU / 真侧车。所有外部调用均模拟不可达。
"""

from __future__ import annotations

import pytest

from services.aria_director import (
    AriaDirectorInput,
    AriaDirectorState,
    AriaPerception,
    _heuristic,
)
from services.aria_media import (
    EchoDriveInput,
    TtsInput,
    request_echo_drive,
    runtime_features,
    synthesize_tts,
)


class TestE2EDirectorPerception:
    """Director + Perception 集成链路。"""

    def test_director_with_perception_produces_brief(self):
        """Director 有感知 → 输出 perception_brief。"""
        inp = AriaDirectorInput(
            event="wake",
            state=AriaDirectorState(
                perception=AriaPerception(
                    objects=["grand_piano", "bookshelf"],
                    lighting="warm_afternoon",
                    mood="focused_practice",
                    time_of_day="afternoon",
                ),
            ),
        )
        out = _heuristic(inp)
        # P1: 感知影响行为
        assert "piano" in (out.utterance or "").lower()
        assert out.perception_brief != ""
        assert "grand_piano" in out.perception_brief

    def test_perception_nudge_influences_action(self):
        """感知到钢琴 → Director 选 play_piano。"""
        from unittest.mock import patch
        from services.aria_director import _perception_nudge

        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(objects=["grand_piano"]),
            ),
        )
        assert _perception_nudge(inp) == "play_piano"

        # 固定随机数避免 40% 概率的 autonomous_speak 干扰
        with patch("services.aria_director.random.random", return_value=0.9):
            out = _heuristic(inp)
        assert out.action == "play_piano"


class TestE2ETtsEchoDegradation:
    """TTS → EchoDrive 降级链路。"""

    @pytest.mark.asyncio
    async def test_tts_succeeds_without_echo(self, monkeypatch: pytest.MonkeyPatch):
        """TTS 正常 + EchoDrive 降级 → 音频仍可播放。"""
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)

        # TTS 可能成功（edge-tts 存在）或失败（无网络）
        tts = await synthesize_tts(TtsInput(text="Hello Aria"))
        # 不管 TTS 是否成功，EchoDrive 应该降级
        echo = await request_echo_drive(
            EchoDriveInput(
                audio_b64=tts.audio_b64 or "A" * 200,
                hand_pose={"pattern_label": "melody", "finger_spread": 0.3},
            )
        )
        assert not echo.ok
        assert echo.degrade
        # 前端应该继续使用 P2 模拟（不报错）

    @pytest.mark.asyncio
    async def test_full_pipeline_no_echo_url(self, monkeypatch: pytest.MonkeyPatch):
        """完整管线：Director → TTS → EchoDrive，无 ECHO_BASE_URL。"""
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)

        # Step 1: Director 决策
        inp = AriaDirectorInput(
            event="user_message",
            message="hello",
            state=AriaDirectorState(
                perception=AriaPerception(objects=["grand_piano"]),
            ),
        )
        director_out = _heuristic(inp)
        assert director_out.utterance is not None

        # Step 2: TTS（可能成功）
        tts = await synthesize_tts(TtsInput(text=director_out.utterance))

        # Step 3: EchoDrive（必然降级）
        if tts.ok and tts.audio_b64:
            echo = await request_echo_drive(
                EchoDriveInput(
                    audio_b64=tts.audio_b64,
                    hand_pose=None,
                )
            )
            assert echo.degrade  # 降级但无异常
        else:
            # TTS 也失败了 → 前端 Web Speech 兜底
            assert not tts.ok


class TestE2ERuntimeFeatures:
    """Runtime features 完整报告。"""

    def test_all_phases_reported(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)
        feats = runtime_features()

        assert feats["director"] is True
        assert feats["autonomous_tick"] is True
        assert feats["perception"] is True
        assert feats["echo_drive"] is False  # 未配置
        assert feats["echo_degrade_to_p2"] is True  # 始终可用

    def test_echo_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ECHO_BASE_URL", "http://echomimic:8080")
        feats = runtime_features()
        assert feats["echo_drive"] is True
