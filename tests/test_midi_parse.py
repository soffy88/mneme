"""MIDI 解析 oprim 单元测试 — vendor/oprim/midi_parse.py"""

from __future__ import annotations

import pytest

from vendor.oprim.midi_parse import (
    MidiEvent,
    MidiFeature,
    midi_to_keyboard_position,
    parse_midi_events,
    parse_note_sequence,
)


class TestMidiEvent:
    def test_default_velocity(self):
        e = MidiEvent(note=60)
        assert e.velocity == 80

    def test_custom_fields(self):
        e = MidiEvent(note=72, time_ms=100.0, duration_ms=250.0, velocity=100)
        assert e.note == 72
        assert e.time_ms == 100.0


class TestParseMidiEvents:
    def test_empty_events(self):
        f = parse_midi_events([])
        assert f.note_count == 0

    def test_single_note(self):
        f = parse_midi_events([MidiEvent(60, 0)])
        assert f.note_count == 1
        assert f.pattern == "single"

    def test_chord_detection(self):
        """同时发声的 3 音 → chord"""
        events = [
            MidiEvent(60, 0),
            MidiEvent(64, 10),  # 10ms 内 = 同时
            MidiEvent(67, 20),
        ]
        f = parse_midi_events(events)
        assert f.pattern == "chord"
        assert f.has_chord is True

    def test_arpeggio_detection(self):
        """快速连续上行 → arpeggio"""
        events = [
            MidiEvent(60, 0),
            MidiEvent(64, 80),
            MidiEvent(67, 160),
            MidiEvent(72, 240),
        ]
        f = parse_midi_events(events)
        assert f.pattern == "arpeggio"

    def test_scale_detection(self):
        """连续半音/全音进行 → scale"""
        events = [
            MidiEvent(60, 0),
            MidiEvent(62, 500),
            MidiEvent(64, 1000),
            MidiEvent(65, 1500),
        ]
        f = parse_midi_events(events)
        assert f.pattern == "scale"

    def test_bass_detection(self):
        """低音区缓慢旋律 → bass"""
        events = [
            MidiEvent(40, 0),
            MidiEvent(43, 1500),
        ]
        f = parse_midi_events(events)
        assert f.pattern == "bass"
        assert f.is_bass_heavy is True

    def test_melody_default(self):
        """不满足其他条件 → melody"""
        events = [
            MidiEvent(65, 0),
            MidiEvent(72, 800),
            MidiEvent(68, 1600),
        ]
        f = parse_midi_events(events)
        assert f.pattern == "melody"

    def test_hand_zone_left(self):
        """低音区 → left hand"""
        events = [MidiEvent(n, i * 100) for i, n in enumerate([40, 43, 45, 48, 50])]
        f = parse_midi_events(events)
        assert f.hand_zone == "left"

    def test_hand_zone_right(self):
        """高音区 → right hand"""
        events = [MidiEvent(n, i * 100) for i, n in enumerate([76, 79, 81, 84, 88])]
        f = parse_midi_events(events)
        assert f.hand_zone == "right"

    def test_hand_zone_both(self):
        """跨音区 → both hands"""
        events = [MidiEvent(n, i * 100) for i, n in enumerate([48, 60, 72, 84])]
        f = parse_midi_events(events)
        assert f.hand_zone == "both"

    def test_density_computation(self):
        """4 音 / 0.75 秒 = density ~5.33"""
        events = [
            MidiEvent(60, 0),
            MidiEvent(64, 250),
            MidiEvent(67, 500),
            MidiEvent(72, 750),
        ]
        f = parse_midi_events(events)
        # 4 notes over 750ms = 5.33 notes/sec
        assert 5.0 < f.density < 6.0

    def test_pitch_range(self):
        events = [MidiEvent(60, 0), MidiEvent(72, 100)]
        f = parse_midi_events(events)
        assert f.pitch_range == 12

    def test_avg_pitch(self):
        events = [MidiEvent(60, 0), MidiEvent(72, 100)]
        f = parse_midi_events(events)
        assert f.avg_pitch == 66.0


class TestParseNoteSequence:
    def test_simple_sequence(self):
        """pianoAmbience 风格的 note 列表"""
        notes = [61, 64, 68, 73, 68, 64, 61, 56]
        f = parse_note_sequence(notes, bpm=52)
        assert f.note_count == 8
        assert f.pattern in ("arpeggio", "melody")

    def test_quiet_river_preset(self):
        """TRACK_PRESETS[1] 的 notes"""
        notes = [57, 61, 64, 69, 64, 61, 57, 52]
        f = parse_note_sequence(notes, bpm=58)
        assert f.note_count == 8
        assert 50 < f.avg_pitch < 70

    def test_empty_sequence(self):
        f = parse_note_sequence([], bpm=60)
        assert f.note_count == 0


class TestMidiToKeyboardPosition:
    def test_middle_c(self):
        """中央 C = 60 → ~0.44 位置"""
        pos, zone = midi_to_keyboard_position(60)
        assert 0.40 < pos < 0.50
        assert zone == "both"

    def test_low_a(self):
        """A0 = 21 → 0.0 位置"""
        pos, zone = midi_to_keyboard_position(21)
        assert pos == 0.0
        assert zone == "left"

    def test_high_c(self):
        """C8 = 108 → 1.0 位置"""
        pos, zone = midi_to_keyboard_position(108)
        assert pos == 1.0
        assert zone == "right"

    def test_left_zone(self):
        """低音区 → left hand"""
        pos, zone = midi_to_keyboard_position(36)  # C2
        assert zone == "left"
        assert pos < 0.3

    def test_right_zone(self):
        """高音区 → right hand"""
        pos, zone = midi_to_keyboard_position(84)  # C6
        assert zone == "right"
        assert pos > 0.7

    def test_out_of_range_clamped(self):
        """超出钢琴范围 → 截断到边界"""
        pos_low, _ = midi_to_keyboard_position(0)
        pos_high, _ = midi_to_keyboard_position(127)
        assert pos_low == 0.0
        assert pos_high == 1.0


class TestMidiFeature:
    def test_to_dict(self):
        f = MidiFeature(
            pattern="chord",
            hand_zone="both",
            note_count=3,
            avg_pitch=64.5,
            pitch_range=7,
            density=2.5,
        )
        d = f.to_dict()
        assert d["pattern"] == "chord"
        assert d["hand_zone"] == "both"
        assert d["avg_pitch"] == 64.5
        assert d["density"] == 2.5
