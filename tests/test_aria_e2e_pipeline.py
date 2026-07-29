"""Aria E2E Pipeline Integration — 全链路降级测试。

验证 P0-P3 完整管线：
  Director → perception + hand_choreo → TTS → EchoDrive → 降级

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
from vendor.oprim.midi_parse import MidiFeature, parse_note_sequence
from vendor.oskill.hand_choreo import choreograph_hands


class TestE2EDirectorPerceptionChoreo:
    """Director + Perception + Hand Choreo 集成链路。"""

    def test_director_with_perception_produces_choreo(self):
        """Director 有感知 → 输出 hand_choreo + perception_brief。"""
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
        # P2: 手部编排存在
        assert out.hand_choreo is not None
        assert out.hand_choreo["pattern_label"] in ("melody", "gesture", "idle", "chord")

    def test_midi_to_choreo_to_director_pipeline(self):
        """MIDI notes → feature → choreo → dict（P2 完整链路）。"""
        # 模拟 pianoAmbience TRACK_PRESETS[0]
        notes = [61, 64, 68, 73, 68, 64, 61, 56]
        feature = parse_note_sequence(notes, bpm=52)
        assert feature.note_count == 8

        choreo = choreograph_hands(feature)
        assert choreo.pattern_label in ("arpeggio", "melody")
        assert 0 <= choreo.finger_spread <= 1.0

        d = choreo.to_dict()
        # 验证可直接 JSON 序列化（前端接收）
        import json
        json.dumps(d)

    def test_perception_nudge_influences_choreo(self):
        """感知到钢琴 → Director 选 play_piano → choreo 用 melody 特征。"""
        from services.aria_director import _perception_nudge

        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(objects=["grand_piano"]),
            ),
        )
        assert _perception_nudge(inp) == "play_piano"

        out = _heuristic(inp)
        assert out.action == "play_piano"
        assert out.hand_choreo is not None


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
                    hand_pose=director_out.hand_choreo,
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

        # P0
        assert feats["director"] is True
        assert feats["cinema_layer"] is True
        assert feats["gsap_keys"] is True
        assert feats["clip_pool"] is True
        assert feats["autonomous_tick"] is True

        # P1
        assert feats["perception"] is True

        # P2
        assert feats["hand_choreo"] is True

        # P3
        assert feats["echo_drive"] is False  # 未配置
        assert feats["echo_degrade_to_p2"] is True  # 始终可用

    def test_echo_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ECHO_BASE_URL", "http://echomimic:8080")
        feats = runtime_features()
        assert feats["echo_drive"] is True
