"""手部编排 oskill — 将 MIDI 特征转换为 GSAP 动画参数。

组合 oprim:
  - vendor.oprim.midi_parse: MidiFeature, midi_to_keyboard_position

输入：MidiFeature（演奏特征）+ 可选键盘位置
输出：HandChoreoParams（GSAP 可用的动画参数）

3O 合规：
  - 可调用 sibling oskill: 无
  - 依赖 oprim: midi_parse
  - stateless: 是
  - 不持久化
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vendor.oprim.midi_parse import (
    HandZone,
    MidiFeature,
    NotePattern,
    midi_to_keyboard_position,
)

if TYPE_CHECKING:
    pass


# ── Types ──────────────────────────────────────────────────────────────────────


@dataclass
class HandChoreoParams:
    """GSAP 手部动画参数。

    用于驱动前端 AriaHands.tsx 组件：
    - left/right hand: 各自的 x/y 位置、旋转、缩放
    - finger_spread: 手指张开程度（和弦时更大）
    - wrist_bounce: 手腕弹跳幅度（琶音/音阶时更明显）
    - attack_intensity: 触键力度（velocity 映射）
    """

    # 左手参数
    left_x_pct: float = 35.0  # 左手 x 位置（% of person layer width）
    left_y_pct: float = 78.0  # 左手 y 位置（% of person layer height）
    left_rotation: float = -5.0  # 左手旋转角度（度）
    left_scale: float = 1.0

    # 右手参数
    right_x_pct: float = 65.0
    right_y_pct: float = 78.0
    right_rotation: float = 5.0
    right_scale: float = 1.0

    # 全局动画参数
    finger_spread: float = 0.3  # 0-1, 手指张开程度
    wrist_bounce: float = 0.2  # 0-1, 手腕弹跳幅度
    attack_intensity: float = 0.6  # 0-1, 触键力度
    transition_ms: int = 180  # 动画过渡时长

    # 当前激活的手
    active_hand: HandZone = "both"

    # 音型描述（用于前端 debug 显示）
    pattern_label: str = "melody"

    def to_dict(self) -> dict:
        return {
            "left_x_pct": round(self.left_x_pct, 1),
            "left_y_pct": round(self.left_y_pct, 1),
            "left_rotation": round(self.left_rotation, 1),
            "left_scale": round(self.left_scale, 2),
            "right_x_pct": round(self.right_x_pct, 1),
            "right_y_pct": round(self.right_y_pct, 1),
            "right_rotation": round(self.right_rotation, 1),
            "right_scale": round(self.right_scale, 2),
            "finger_spread": round(self.finger_spread, 2),
            "wrist_bounce": round(self.wrist_bounce, 2),
            "attack_intensity": round(self.attack_intensity, 2),
            "transition_ms": self.transition_ms,
            "active_hand": self.active_hand,
            "pattern_label": self.pattern_label,
        }


# ── Pattern → Params mapping ──────────────────────────────────────────────────

# 钢琴键盘位置映射（88 键归一化 0-1）
# 左手通常覆盖 21-60 (A0-C4)，右手 60-108 (C4-C8)
_LEFT_REST_X = 35.0  # 左手静息 x%
_RIGHT_REST_X = 65.0  # 右手静息 x%
_HAND_Y_BASE = 78.0  # 手部 y% baseline


def _pattern_to_spread(pattern: NotePattern) -> float:
    """音型 → 手指张开程度。"""
    spreads = {
        "chord": 0.85,       # 和弦：手指大张
        "arpeggio": 0.5,     # 琶音：中等
        "scale": 0.35,       # 音阶：较收
        "melody": 0.3,       # 旋律：自然
        "bass": 0.4,         # 低音：略张
        "single": 0.2,       # 单音：放松
    }
    return spreads.get(pattern, 0.3)


def _pattern_to_bounce(pattern: NotePattern) -> float:
    """音型 → 手腕弹跳幅度。"""
    bounces = {
        "chord": 0.6,        # 和弦：明显弹跳
        "arpeggio": 0.75,    # 琶音：流畅波浪
        "scale": 0.5,        # 音阶：平稳推进
        "melody": 0.4,       # 旋律：轻微起伏
        "bass": 0.3,         # 低音：沉稳
        "single": 0.15,      # 单音：最小
    }
    return bounces.get(pattern, 0.4)


def _pattern_to_transition(pattern: NotePattern, density: float) -> int:
    """音型 + 密度 → 过渡时长 ms。"""
    base = {
        "chord": 120,
        "arpeggio": 150,
        "scale": 140,
        "melody": 180,
        "bass": 200,
        "single": 220,
    }
    ms = base.get(pattern, 180)
    # 高密度 → 更快过渡
    if density > 3.0:
        ms = int(ms * 0.7)
    elif density > 2.0:
        ms = int(ms * 0.85)
    return max(80, min(ms, 300))


# ── Main oskill ────────────────────────────────────────────────────────────────


def choreograph_hands(
    feature: MidiFeature,
    *,
    target_note: int | None = None,
) -> HandChoreoParams:
    """根据 MIDI 特征编排手部动画参数。

    Parameters
    ----------
    feature : MidiFeature
        从 midi_parse.parse_midi_events 获取的演奏特征
    target_note : int | None
        可选：当前正在弹奏的 MIDI note，用于精确键盘定位

    Returns
    -------
    HandChoreoParams
        GSAP 可用的动画参数

    Examples
    --------
    >>> from vendor.oprim.midi_parse import MidiFeature
    >>> f = MidiFeature(pattern="chord", hand_zone="both", density=2.5)
    >>> h = choreograph_hands(f)
    >>> h.finger_spread
    0.85
    >>> h.wrist_bounce
    0.6
    """
    pattern = feature.pattern
    hand_zone = feature.hand_zone
    density = feature.density

    # 基础参数
    left_x = _LEFT_REST_X
    right_x = _RIGHT_REST_X
    left_y = _HAND_Y_BASE
    right_y = _HAND_Y_BASE
    left_rot = -5.0
    right_rot = 5.0
    left_scale = 1.0
    right_scale = 1.0

    # 如果有 target_note，精确定位
    if target_note is not None:
        key_pos, note_zone = midi_to_keyboard_position(target_note)
        # key_pos 0-1 映射到 x% 20-80 范围
        target_x = 20.0 + key_pos * 60.0

        if note_zone == "left":
            left_x = target_x
            left_y = _HAND_Y_BASE - 2
            left_rot = -8.0 - key_pos * 5
        elif note_zone == "right":
            right_x = target_x
            right_y = _HAND_Y_BASE - 2
            right_rot = 3.0 + key_pos * 5
        else:  # both zone
            if key_pos < 0.45:
                left_x = target_x
            else:
                right_x = target_x

    # 音型特定调整
    if pattern == "chord":
        # 和弦：双手靠近
        if hand_zone == "both":
            mid_x = (left_x + right_x) / 2
            left_x = mid_x - 8
            right_x = mid_x + 8
        left_scale = 1.05
        right_scale = 1.05

    elif pattern == "arpeggio":
        # 琶音：手部波浪运动（y 偏移）
        left_y += 2.0
        right_y += 2.0
        left_rot += 3.0
        right_rot -= 3.0

    elif pattern == "scale":
        # 音阶：手部水平滑动
        if feature.avg_pitch > 65:
            left_x += 5
            right_x += 5
        elif feature.avg_pitch < 55:
            left_x -= 5
            right_x -= 5

    elif pattern == "bass":
        # 低音：左手主导
        left_scale = 1.08
        left_y -= 3
        right_x = _RIGHT_REST_X + 10  # 右手退后
        right_scale = 0.95

    # 密度影响攻击感
    attack = min(1.0, 0.4 + density * 0.15)
    if feature.is_bass_heavy:
        attack = min(1.0, attack + 0.1)

    return HandChoreoParams(
        left_x_pct=left_x,
        left_y_pct=left_y,
        left_rotation=left_rot,
        left_scale=left_scale,
        right_x_pct=right_x,
        right_y_pct=right_y,
        right_rotation=right_rot,
        right_scale=right_scale,
        finger_spread=_pattern_to_spread(pattern),
        wrist_bounce=_pattern_to_bounce(pattern),
        attack_intensity=attack,
        transition_ms=_pattern_to_transition(pattern, density),
        active_hand=hand_zone,
        pattern_label=pattern,
    )


def idle_hands() -> HandChoreoParams:
    """静息手部参数（非弹琴状态）。"""
    return HandChoreoParams(
        left_x_pct=40.0,
        left_y_pct=72.0,
        left_rotation=-10.0,
        left_scale=0.95,
        right_x_pct=60.0,
        right_y_pct=72.0,
        right_rotation=10.0,
        right_scale=0.95,
        finger_spread=0.15,
        wrist_bounce=0.05,
        attack_intensity=0.1,
        transition_ms=400,
        active_hand="both",
        pattern_label="idle",
    )


def gesture_hands(intensity: float = 0.5) -> HandChoreoParams:
    """说话/对话时的手势参数。"""
    return HandChoreoParams(
        left_x_pct=38.0,
        left_y_pct=65.0 - intensity * 8,
        left_rotation=-15.0 + intensity * 5,
        left_scale=0.9 + intensity * 0.1,
        right_x_pct=62.0,
        right_y_pct=65.0 - intensity * 8,
        right_rotation=15.0 - intensity * 5,
        right_scale=0.9 + intensity * 0.1,
        finger_spread=0.25 + intensity * 0.15,
        wrist_bounce=0.1 + intensity * 0.2,
        attack_intensity=intensity * 0.4,
        transition_ms=250,
        active_hand="both",
        pattern_label="gesture",
    )
