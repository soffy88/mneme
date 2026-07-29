"""MIDI 事件解析原子操作 — 从音符序列提取演奏特征。

输入：MIDI note 列表（0-127 整数，Web Audio 使用的标准 MIDI 编号）
输出：演奏特征（手区、音型类型、节奏密度）

用于 P2 手部动画同步：前端 pianoAmbience 生成音符 → 此 oprim 分析 → hand_choreo 驱动 GSAP。

不依赖外部 MIDI 文件库；纯 Python 计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence


# ── Types ──────────────────────────────────────────────────────────────────────

NotePattern = Literal["chord", "arpeggio", "scale", "melody", "bass", "single"]
HandZone = Literal["left", "right", "both"]


@dataclass(frozen=True)
class MidiEvent:
    """单个音符事件。"""

    note: int  # MIDI 0-127
    time_ms: float = 0.0  # 相对起始时间
    duration_ms: float = 500.0
    velocity: int = 80  # 0-127


@dataclass
class MidiFeature:
    """从音符序列提取的演奏特征。"""

    pattern: NotePattern = "melody"
    hand_zone: HandZone = "both"
    note_count: int = 0
    avg_pitch: float = 60.0
    pitch_range: int = 12
    density: float = 1.0  # notes per second
    is_bass_heavy: bool = False
    has_chord: bool = False

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "hand_zone": self.hand_zone,
            "note_count": self.note_count,
            "avg_pitch": round(self.avg_pitch, 1),
            "pitch_range": self.pitch_range,
            "density": round(self.density, 2),
            "is_bass_heavy": self.is_bass_heavy,
            "has_chord": self.has_chord,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

# 钢琴键盘：中央 C = 60，低音区 < 52，高音区 > 72
_BASS_THRESHOLD = 52
_TREBLE_THRESHOLD = 72
_MIDDLE_C = 60

# 和弦检测：同时发声的音符（时间窗口 50ms 内）
_CHORD_WINDOW_MS = 50.0
_CHORD_MIN_NOTES = 3

# 琶音检测：快速连续音符（间隔 < 150ms）
_ARPEGGIO_MAX_GAP_MS = 150.0
_ARPEGGIO_MIN_NOTES = 3

# 音阶检测：连续半音/全音进行
_SCALE_INTERVALS = {1, 2}  # semitone steps


def _classify_hand_zone(notes: Sequence[int]) -> HandZone:
    """根据音高分布判断主要手部区域。"""
    if not notes:
        return "both"

    bass_count = sum(1 for n in notes if n < _BASS_THRESHOLD)
    treble_count = sum(1 for n in notes if n > _TREBLE_THRESHOLD)
    total = len(notes)

    if total == 0:
        return "both"

    bass_ratio = bass_count / total
    treble_ratio = treble_count / total

    if bass_ratio > 0.6:
        return "left"
    if treble_ratio > 0.6:
        return "right"
    return "both"


def _detect_chord(events: Sequence[MidiEvent]) -> bool:
    """检测是否存在和弦（同时发声 ≥3 音）。"""
    if len(events) < _CHORD_MIN_NOTES:
        return False

    sorted_events = sorted(events, key=lambda e: e.time_ms)
    for i, e in enumerate(sorted_events):
        window_notes = [
            ev for ev in sorted_events[i : i + 8]
            if ev.time_ms - e.time_ms <= _CHORD_WINDOW_MS
        ]
        if len(window_notes) >= _CHORD_MIN_NOTES:
            return True
    return False


def _detect_arpeggio(events: Sequence[MidiEvent]) -> bool:
    """检测是否为琶音（快速连续上行/下行）。"""
    if len(events) < _ARPEGGIO_MIN_NOTES:
        return False

    sorted_events = sorted(events, key=lambda e: e.time_ms)
    consecutive_fast = 0
    direction = 0  # 1=up, -1=down, 0=mixed

    for i in range(1, len(sorted_events)):
        gap = sorted_events[i].time_ms - sorted_events[i - 1].time_ms
        pitch_diff = sorted_events[i].note - sorted_events[i - 1].note

        if gap <= _ARPEGGIO_MAX_GAP_MS:
            consecutive_fast += 1
            if pitch_diff > 0:
                if direction == 0:
                    direction = 1
                elif direction == -1:
                    consecutive_fast = 1
                    direction = 1
            elif pitch_diff < 0:
                if direction == 0:
                    direction = -1
                elif direction == 1:
                    consecutive_fast = 1
                    direction = -1
        else:
            consecutive_fast = 0
            direction = 0

        if consecutive_fast >= _ARPEGGIO_MIN_NOTES - 1:
            return True

    return False


def _detect_scale(events: Sequence[MidiEvent]) -> bool:
    """检测是否为音阶进行（连续半音/全音）。"""
    if len(events) < 4:
        return False

    sorted_events = sorted(events, key=lambda e: e.time_ms)
    scale_steps = 0

    for i in range(1, len(sorted_events)):
        interval = abs(sorted_events[i].note - sorted_events[i - 1].note)
        if interval in _SCALE_INTERVALS:
            scale_steps += 1
        else:
            scale_steps = 0

        if scale_steps >= 3:  # 4 consecutive scale steps
            return True

    return False


def _compute_density(events: Sequence[MidiEvent]) -> float:
    """计算音符密度（notes per second）。"""
    if len(events) < 2:
        return 0.0

    sorted_events = sorted(events, key=lambda e: e.time_ms)
    duration_s = (sorted_events[-1].time_ms - sorted_events[0].time_ms) / 1000.0
    if duration_s < 0.1:
        return float(len(events))
    return len(events) / duration_s


# ── Main oprim ─────────────────────────────────────────────────────────────────


def parse_midi_events(events: Sequence[MidiEvent]) -> MidiFeature:
    """解析 MIDI 事件序列，提取演奏特征。

    Parameters
    ----------
    events : Sequence[MidiEvent]
        MIDI 音符事件列表（note 0-127）

    Returns
    -------
    MidiFeature
        演奏特征（pattern, hand_zone, density 等）

    Examples
    --------
    >>> events = [MidiEvent(60, 0), MidiEvent(64, 100), MidiEvent(67, 200)]
    >>> f = parse_midi_events(events)
    >>> f.pattern
    'arpeggio'
    >>> f.hand_zone
    'right'
    """
    if not events:
        return MidiFeature(note_count=0)

    notes = [e.note for e in events]
    avg_pitch = sum(notes) / len(notes)
    pitch_range = max(notes) - min(notes) if notes else 0

    # 分类 pattern
    has_chord = _detect_chord(events)
    has_arpeggio = _detect_arpeggio(events)
    has_scale = _detect_scale(events)
    density = _compute_density(events)

    if has_chord:
        pattern: NotePattern = "chord"
    elif has_arpeggio:
        pattern = "arpeggio"
    elif has_scale:
        pattern = "scale"
    elif len(events) == 1:
        pattern = "single"
    elif density < 1.5 and avg_pitch < _BASS_THRESHOLD:
        pattern = "bass"
    else:
        pattern = "melody"

    hand_zone = _classify_hand_zone(notes)
    is_bass_heavy = avg_pitch < _MIDDLE_C - 6

    return MidiFeature(
        pattern=pattern,
        hand_zone=hand_zone,
        note_count=len(events),
        avg_pitch=avg_pitch,
        pitch_range=pitch_range,
        density=density,
        is_bass_heavy=is_bass_heavy,
        has_chord=has_chord,
    )


def parse_note_sequence(notes: Sequence[int], bpm: float = 60.0) -> MidiFeature:
    """简化入口：从 MIDI note 列表生成均匀间隔的事件。

    用于前端 pianoAmbience 的 TRACK_PRESETS.notes 直接分析。

    Parameters
    ----------
    notes : Sequence[int]
        MIDI note 列表（0-127）
    bpm : float
        节拍速度（用于计算时间间隔）

    Returns
    -------
    MidiFeature
    """
    beat_ms = (60.0 / bpm) * 1000.0
    events = [
        MidiEvent(note=n, time_ms=i * beat_ms, duration_ms=beat_ms * 0.8)
        for i, n in enumerate(notes)
    ]
    return parse_midi_events(events)


def midi_to_keyboard_position(note: int) -> tuple[float, HandZone]:
    """将 MIDI note 转换为钢琴键盘位置（0-1 归一化）和手部区域。

    标准 88 键钢琴：A0=21, C8=108
    位置 0.0 = 最左（低音 A0），1.0 = 最右（高音 C8）

    Parameters
    ----------
    note : int
        MIDI note 编号（0-127）

    Returns
    -------
    tuple[float, HandZone]
        (keyboard_position 0-1, hand_zone)
    """
    # 88 键钢琴范围
    PIANO_MIN = 21  # A0
    PIANO_MAX = 108  # C8

    clamped = max(PIANO_MIN, min(PIANO_MAX, note))
    position = (clamped - PIANO_MIN) / (PIANO_MAX - PIANO_MIN)

    # 键盘中线（中央 C = 60）对应位置 ~0.44
    middle_position = (_MIDDLE_C - PIANO_MIN) / (PIANO_MAX - PIANO_MIN)

    if position < middle_position - 0.15:
        zone: HandZone = "left"
    elif position > middle_position + 0.15:
        zone = "right"
    else:
        zone = "both"

    return position, zone
