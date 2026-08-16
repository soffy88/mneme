"""手部编排 oskill 单元测试 — vendor/oskill/hand_choreo.py"""

from __future__ import annotations

from oprim.midi_parse import MidiFeature
from oskill.hand_choreo import (
    HandChoreoParams,
    choreograph_hands,
    gesture_hands,
    idle_hands,
)


class TestChoreographHands:
    def test_chord_pattern(self):
        """和弦 → 高 finger_spread + 双手靠近"""
        f = MidiFeature(
            pattern="chord",
            hand_zone="both",
            note_count=3,
            avg_pitch=64.0,
            density=2.0,
        )
        h = choreograph_hands(f)
        assert h.finger_spread >= 0.8
        assert h.wrist_bounce >= 0.5
        assert h.pattern_label == "chord"

    def test_arpeggio_pattern(self):
        """琶音 → 中等 spread + 流畅 bounce"""
        f = MidiFeature(
            pattern="arpeggio",
            hand_zone="right",
            note_count=6,
            avg_pitch=68.0,
            density=3.0,
        )
        h = choreograph_hands(f)
        assert 0.4 <= h.finger_spread <= 0.7
        assert h.wrist_bounce >= 0.6
        assert h.pattern_label == "arpeggio"

    def test_scale_pattern(self):
        """音阶 → 较低 spread + 平稳 bounce"""
        f = MidiFeature(
            pattern="scale",
            hand_zone="right",
            note_count=8,
            avg_pitch=70.0,
            density=2.5,
        )
        h = choreograph_hands(f)
        assert h.finger_spread < 0.5
        assert h.pattern_label == "scale"

    def test_bass_pattern(self):
        """低音 → 左手主导 + 较大 scale"""
        f = MidiFeature(
            pattern="bass",
            hand_zone="left",
            note_count=2,
            avg_pitch=45.0,
            density=1.0,
            is_bass_heavy=True,
        )
        h = choreograph_hands(f)
        assert h.left_scale > h.right_scale
        assert h.pattern_label == "bass"

    def test_target_note_positioning(self):
        """指定 target_note → 精确键盘定位"""
        f = MidiFeature(pattern="melody", hand_zone="right")
        # 高音 C (72) → 右手区
        h = choreograph_hands(f, target_note=72)
        assert h.right_x_pct > 55
        # 低音 C (48) → 左手区
        h2 = choreograph_hands(f, target_note=48)
        assert h2.left_x_pct < 45

    def test_density_affects_transition(self):
        """高密度 → 更短过渡时间"""
        f_low = MidiFeature(pattern="melody", density=1.0)
        f_high = MidiFeature(pattern="melody", density=4.0)
        h_low = choreograph_hands(f_low)
        h_high = choreograph_hands(f_high)
        assert h_high.transition_ms < h_low.transition_ms

    def test_attack_intensity_bounded(self):
        """attack_intensity 始终在 0-1 范围"""
        for density in [0.5, 1.0, 2.0, 5.0, 10.0]:
            f = MidiFeature(pattern="melody", density=density, is_bass_heavy=True)
            h = choreograph_hands(f)
            assert 0.0 <= h.attack_intensity <= 1.0

    def test_to_dict_serializable(self):
        """to_dict() 返回可 JSON 序列化的 dict"""
        f = MidiFeature(pattern="chord", hand_zone="both", density=2.0)
        h = choreograph_hands(f)
        d = h.to_dict()
        assert isinstance(d, dict)
        assert "left_x_pct" in d
        assert "finger_spread" in d
        assert "active_hand" in d
        # 所有数值都是可序列化的
        import json
        json.dumps(d)  # 不应抛异常


class TestIdleHands:
    def test_idle_params(self):
        h = idle_hands()
        assert h.pattern_label == "idle"
        assert h.finger_spread < 0.2
        assert h.wrist_bounce < 0.1
        assert h.attack_intensity < 0.2
        assert h.transition_ms > 300  # 较慢过渡

    def test_idle_to_dict(self):
        d = idle_hands().to_dict()
        assert d["pattern_label"] == "idle"


class TestGestureHands:
    def test_gesture_low_intensity(self):
        h = gesture_hands(intensity=0.2)
        assert h.pattern_label == "gesture"
        assert h.finger_spread < 0.35

    def test_gesture_high_intensity(self):
        h = gesture_hands(intensity=0.9)
        assert h.finger_spread > 0.35
        assert h.left_y_pct < 62  # 手抬高

    def test_gesture_default_intensity(self):
        h = gesture_hands()
        assert 0.3 < h.finger_spread < 0.5


class TestHandChoreoParams:
    def test_defaults(self):
        h = HandChoreoParams()
        assert 0 <= h.left_x_pct <= 100
        assert 0 <= h.right_x_pct <= 100
        assert h.active_hand == "both"

    def test_all_fields_present(self):
        h = HandChoreoParams()
        d = h.to_dict()
        expected_keys = {
            "left_x_pct", "left_y_pct", "left_rotation", "left_scale",
            "right_x_pct", "right_y_pct", "right_rotation", "right_scale",
            "finger_spread", "wrist_bounce", "attack_intensity",
            "transition_ms", "active_hand", "pattern_label",
        }
        assert set(d.keys()) == expected_keys


class TestDirectorHandChoreo:
    """验证 Director 输出包含 hand_choreo 字段。"""

    def test_heuristic_play_piano_has_choreo(self):
        from services.aria_director import AriaDirectorInput, _heuristic

        inp = AriaDirectorInput(event="tick")
        out = _heuristic(inp)
        assert out.hand_choreo is not None
        assert out.hand_choreo["pattern_label"] == "melody"

    def test_heuristic_speak_has_gesture_choreo(self):
        from services.aria_director import AriaDirectorInput, _heuristic

        inp = AriaDirectorInput(event="user_message", message="hello")
        out = _heuristic(inp)
        assert out.hand_choreo is not None
        assert out.hand_choreo["pattern_label"] == "gesture"

    def test_heuristic_idle_has_idle_choreo(self):
        from services.aria_director import AriaDirectorInput, AriaDirectorState, _heuristic

        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(mode="conversation"),
        )
        out = _heuristic(inp)
        assert out.hand_choreo is not None
        assert out.hand_choreo["pattern_label"] == "idle"
