"""Aria 数字人 Director（指挥层）。

LLM 输出：
  - action / utterance / emotion
  - layout：人像在画面中的位置与缩放（房间固定）
  - hands：手部动作风格与强度

渲染层只执行；不写掌握度。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

AriaAction = Literal[
    "play_piano",
    "look_at_user",
    "speak",
    "think",
    "return_to_piano",
    "idle",
]

HandStyle = Literal["play", "idle", "gesture", "rest"]


class AriaLayout(BaseModel):
    """人像层 CSS 布局（百分比；房间永不随之动）。"""

    left_pct: float = 30.0
    bottom_pct: float = 2.0
    width_pct: float = 55.0
    height_pct: float = 88.0
    scale: float = 1.0
    # 人像图在容器内的 object-position
    anchor_x_pct: float = 70.0
    anchor_y_pct: float = 100.0


class AriaHands(BaseModel):
    """手部动作参数（GSAP 驱动人像臂区）。"""

    style: HandStyle = "idle"
    intensity: float = 0.55  # 0..1
    rate: float = 1.0  # 相对速度
    reach_x_pct: float = 0.0  # 手臂锚点左右偏移
    reach_y_pct: float = 0.0


# 经校准的默认：弹琴坐凳偏右、对话居中偏左
_LAYOUT_PRESETS: dict[str, AriaLayout] = {
    "play_piano": AriaLayout(
        left_pct=38,
        bottom_pct=0,
        width_pct=58,
        height_pct=92,
        scale=1.08,
        anchor_x_pct=78,
        anchor_y_pct=100,
    ),
    "return_to_piano": AriaLayout(
        left_pct=38,
        bottom_pct=0,
        width_pct=58,
        height_pct=92,
        scale=1.08,
        anchor_x_pct=78,
        anchor_y_pct=100,
    ),
    "look_at_user": AriaLayout(
        left_pct=18,
        bottom_pct=4,
        width_pct=64,
        height_pct=86,
        scale=1.02,
        anchor_x_pct=42,
        anchor_y_pct=100,
    ),
    "speak": AriaLayout(
        left_pct=16,
        bottom_pct=4,
        width_pct=66,
        height_pct=88,
        scale=1.04,
        anchor_x_pct=40,
        anchor_y_pct=100,
    ),
    "think": AriaLayout(
        left_pct=22,
        bottom_pct=5,
        width_pct=60,
        height_pct=84,
        scale=1.0,
        anchor_x_pct=45,
        anchor_y_pct=100,
    ),
    "idle": AriaLayout(
        left_pct=20,
        bottom_pct=4,
        width_pct=62,
        height_pct=85,
        scale=1.01,
        anchor_x_pct=44,
        anchor_y_pct=100,
    ),
}

_HANDS_PRESETS: dict[str, AriaHands] = {
    "play_piano": AriaHands(style="play", intensity=0.85, rate=1.15, reach_x_pct=-4, reach_y_pct=2),
    "return_to_piano": AriaHands(
        style="play", intensity=0.7, rate=1.0, reach_x_pct=-3, reach_y_pct=1
    ),
    "look_at_user": AriaHands(style="idle", intensity=0.25, rate=0.6),
    "speak": AriaHands(style="gesture", intensity=0.45, rate=0.9, reach_x_pct=2),
    "think": AriaHands(style="rest", intensity=0.15, rate=0.4),
    "idle": AriaHands(style="idle", intensity=0.2, rate=0.5),
}


DIRECTOR_SYSTEM = """You are the behavioral + stage director for Aria, a photoreal layered digital human.
Background room is FIXED. You only control the PERSON layer (layout + hands) and behavior.

Available actions:
- play_piano: sit on the bench at the grand piano, play (hands on keys)
- look_at_user / speak / think / return_to_piano / idle

Output ONLY valid JSON:
{
  "action": "play_piano|look_at_user|speak|think|return_to_piano|idle",
  "utterance": "English speech or null",
  "emotion": "focused|warm|gentle|curious|thoughtful",
  "hold_ms": 2000,
  "reason": "short note",
  "layout": {
    "left_pct": 0-70,
    "bottom_pct": 0-25,
    "width_pct": 40-90,
    "height_pct": 60-100,
    "scale": 0.7-1.35,
    "anchor_x_pct": 0-100,
    "anchor_y_pct": 80-100
  },
  "hands": {
    "style": "play|idle|gesture|rest",
    "intensity": 0-1,
    "rate": 0.3-2.0,
    "reach_x_pct": -20-20,
    "reach_y_pct": -15-15
  }
}

Stage calibration (must follow unless user asks to adjust):
- play_piano: person sits on RIGHT bench near keyboard; left_pct≈35-45, width_pct≈55-65, scale≈1.05-1.15, hands.style=play high intensity
- speak/look_at_user: person more CENTER-LEFT facing camera; left_pct≈12-25, scale≈1.0-1.08, hands.style=gesture or idle
- If user says move left/right/up/down/bigger/smaller/hands faster: ADJUST layout/hands from current_layout accordingly (step ~5-8 pct).
- utterance English when speaking. Never mention JSON/system.

Scene perception (when provided):
- "perception_brief" describes what Aria sees around her (objects, lighting, mood, time).
- USE it to enrich utterances and choose fitting actions. E.g. if "grand_piano" is present, prefer play_piano over idle.
  If "evening" + "warm" lighting, a cozy utterance fits. If "sheet_music" is visible, Aria might comment on the score.
- You may reference perceived objects naturally: "I see the afternoon light on the piano keys."
- Do NOT invent objects not listed in perception_brief.
"""


class AriaPerception(BaseModel):
    """P1 场景感知：前端传入或 VLM 产出，Director 消费。"""

    objects: list[str] = Field(default_factory=list)
    lighting: str = "neutral"
    mood: str = "neutral"
    time_of_day: str = "daytime"
    activity_context: str = "general"
    user_visible: bool = True
    raw_description: str = ""

    def brief(self) -> str:
        parts: list[str] = []
        if self.objects:
            parts.append(f"objects: {', '.join(self.objects[:6])}")
        if self.lighting and self.lighting != "neutral":
            parts.append(f"lighting: {self.lighting}")
        if self.mood and self.mood != "neutral":
            parts.append(f"mood: {self.mood}")
        if self.time_of_day and self.time_of_day != "daytime":
            parts.append(f"time: {self.time_of_day}")
        if self.activity_context and self.activity_context != "general":
            parts.append(f"activity: {self.activity_context}")
        return "; ".join(parts) if parts else ""


class AriaDirectorState(BaseModel):
    mode: str = "playing"
    last_action: str = "play_piano"
    emotion: str = "focused"
    # 前端回传当前布局，便于 LLM 微调
    layout: AriaLayout | None = None
    hands: AriaHands | None = None
    # P1: 场景感知（前端传入或 PerceptionManager 注入）
    perception: AriaPerception | None = None


class AriaDirectorInput(BaseModel):
    event: Literal["tick", "wake", "user_message"] = "tick"
    message: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    state: AriaDirectorState = Field(default_factory=AriaDirectorState)


class AriaDirectorOutput(BaseModel):
    action: AriaAction
    utterance: str | None = None
    emotion: str = "gentle"
    hold_ms: int = 3000
    reason: str = ""
    source: str = "llm"
    layout: AriaLayout = Field(default_factory=AriaLayout)
    hands: AriaHands = Field(default_factory=AriaHands)
    # P1: 回传感知给前端（debug + 对话素材）
    perception_brief: str = ""
    # P2: 手部编排参数（GSAP 动画用；从 midi_parse + hand_choreo 生成）
    hand_choreo: dict[str, Any] | None = None


def _clamp_layout(lay: AriaLayout) -> AriaLayout:
    return AriaLayout(
        left_pct=max(0.0, min(70.0, lay.left_pct)),
        bottom_pct=max(0.0, min(30.0, lay.bottom_pct)),
        width_pct=max(35.0, min(95.0, lay.width_pct)),
        height_pct=max(55.0, min(100.0, lay.height_pct)),
        scale=max(0.65, min(1.4, lay.scale)),
        anchor_x_pct=max(0.0, min(100.0, lay.anchor_x_pct)),
        anchor_y_pct=max(70.0, min(100.0, lay.anchor_y_pct)),
    )


def _clamp_hands(h: AriaHands) -> AriaHands:
    style = h.style if h.style in ("play", "idle", "gesture", "rest") else "idle"
    return AriaHands(
        style=style,  # type: ignore[arg-type]
        intensity=max(0.0, min(1.0, h.intensity)),
        rate=max(0.25, min(2.5, h.rate)),
        reach_x_pct=max(-25.0, min(25.0, h.reach_x_pct)),
        reach_y_pct=max(-20.0, min(20.0, h.reach_y_pct)),
    )


def _preset_for(action: str) -> tuple[AriaLayout, AriaHands]:
    lay = _LAYOUT_PRESETS.get(action, _LAYOUT_PRESETS["idle"]).model_copy()
    hands = _HANDS_PRESETS.get(action, _HANDS_PRESETS["idle"]).model_copy()
    return lay, hands


def _parse_layout(raw: Any, fallback: AriaLayout) -> AriaLayout:
    if not isinstance(raw, dict):
        return fallback
    data = fallback.model_dump()
    for k in data:
        if k in raw and raw[k] is not None:
            try:
                data[k] = float(raw[k])
            except (TypeError, ValueError):
                pass
    return _clamp_layout(AriaLayout(**data))


def _parse_hands(raw: Any, fallback: AriaHands) -> AriaHands:
    if not isinstance(raw, dict):
        return fallback
    data = fallback.model_dump()
    if "style" in raw and raw["style"] in ("play", "idle", "gesture", "rest"):
        data["style"] = raw["style"]
    for k in ("intensity", "rate", "reach_x_pct", "reach_y_pct"):
        if k in raw and raw[k] is not None:
            try:
                data[k] = float(raw[k])
            except (TypeError, ValueError):
                pass
    return _clamp_hands(AriaHands(**data))


def _nudge_layout_from_text(msg: str, lay: AriaLayout) -> tuple[AriaLayout, bool]:
    """用户自然语言微调位置（中英）。"""
    m = (msg or "").lower()
    changed = False
    step = 6.0
    if any(w in m for w in ("left", "左边", "往左", "向左", "靠左")):
        lay.left_pct -= step
        changed = True
    if any(w in m for w in ("right", "右边", "往右", "向右", "靠右")):
        lay.left_pct += step
        changed = True
    if any(w in m for w in ("up", "上移", "往上", "抬高", "高一点")):
        lay.bottom_pct += 3
        changed = True
    if any(w in m for w in ("down", "下移", "往下", "低一点", "坐下")):
        lay.bottom_pct = max(0, lay.bottom_pct - 3)
        changed = True
    if any(w in m for w in ("bigger", "更大", "放大", "大一点", "靠近")):
        lay.scale = min(1.4, lay.scale + 0.08)
        lay.height_pct = min(100, lay.height_pct + 4)
        changed = True
    if any(w in m for w in ("smaller", "更小", "缩小", "小一点", "远一点")):
        lay.scale = max(0.7, lay.scale - 0.08)
        lay.height_pct = max(55, lay.height_pct - 4)
        changed = True
    if any(w in m for w in ("bench", "琴凳", "坐下弹琴", "sit at piano", "on the bench")):
        lay = _LAYOUT_PRESETS["play_piano"].model_copy()
        changed = True
    return _clamp_layout(lay), changed


def _nudge_hands_from_text(msg: str, hands: AriaHands) -> tuple[AriaHands, bool]:
    m = (msg or "").lower()
    changed = False
    if any(w in m for w in ("faster", "快一点", "手快", "急促")):
        hands.rate = min(2.5, hands.rate + 0.25)
        hands.intensity = min(1.0, hands.intensity + 0.1)
        hands.style = "play"
        changed = True
    if any(w in m for w in ("slower", "慢一点", "轻一点", "柔和")):
        hands.rate = max(0.3, hands.rate - 0.2)
        hands.intensity = max(0.1, hands.intensity - 0.1)
        changed = True
    if any(w in m for w in ("hands", "手部", "弹琴手", "play hands", "finger")):
        hands.style = "play"
        hands.intensity = max(hands.intensity, 0.75)
        changed = True
    return _clamp_hands(hands), changed


def _default_hand_choreo(action: str) -> dict[str, Any] | None:
    """P2: 根据 action 生成默认 hand_choreo。"""
    if action in ("play_piano", "return_to_piano"):
        from vendor.oskill.hand_choreo import choreograph_hands
        from vendor.oprim.midi_parse import MidiFeature

        # 默认旋律特征
        feature = MidiFeature(
            pattern="melody",
            hand_zone="both",
            note_count=4,
            avg_pitch=64.0,
            pitch_range=12,
            density=1.5,
        )
        return choreograph_hands(feature).to_dict()
    elif action == "speak":
        from vendor.oskill.hand_choreo import gesture_hands

        return gesture_hands(intensity=0.4).to_dict()
    elif action == "think":
        from vendor.oskill.hand_choreo import idle_hands

        return idle_hands().to_dict()
    else:
        from vendor.oskill.hand_choreo import idle_hands

        return idle_hands().to_dict()


def _with_stage(action: str, base: AriaDirectorOutput | None = None) -> AriaDirectorOutput:
    lay, hands = _preset_for(action)
    choreo = _default_hand_choreo(action)
    if base is None:
        return AriaDirectorOutput(
            action=action, layout=lay, hands=hands, hand_choreo=choreo  # type: ignore[arg-type]
        )
    base.layout = lay
    base.hands = hands
    base.hand_choreo = choreo
    return base


def _perception_nudge(inp: AriaDirectorInput) -> str | None:
    """P1: 基于场景感知建议 action。"""
    perc = inp.state.perception
    if perc is None:
        return None
    objs = {o.lower() for o in perc.objects}
    # 有钢琴 → 倾向弹琴
    if objs & {"grand_piano", "upright_piano", "piano"}:
        return "play_piano"
    # 有乐谱/谱架 → 倾向弹琴
    if objs & {"sheet_music", "music_stand"}:
        return "play_piano"
    # 有沙发/放松氛围 → 倾向对话
    if perc.mood in ("relaxed_conversation", "cozy_intimate"):
        return "speak"
    return None


def _heuristic(inp: AriaDirectorInput) -> AriaDirectorOutput:
    """无 LLM 时的可演示行为 + 布局/手部预设 + 用户纠位置 + 感知。"""
    cur_lay = inp.state.layout or _LAYOUT_PRESETS.get(
        inp.state.last_action, _LAYOUT_PRESETS["idle"]
    )
    cur_hands = inp.state.hands or _HANDS_PRESETS.get(
        inp.state.last_action, _HANDS_PRESETS["idle"]
    )
    perc_brief = inp.state.perception.brief() if inp.state.perception else ""

    if inp.event == "wake":
        # P1: 感知引导唤醒语
        perc = inp.state.perception
        wake_utterance = (
            "Oh — hello. I was just finishing a phrase. "
            "I'm Aria. Would you like to talk for a while?"
        )
        if perc and perc.time_of_day == "evening":
            wake_utterance = (
                "Good evening. The light is lovely tonight. "
                "I'm Aria — shall we share a moment?"
            )
        elif perc and "grand_piano" in {o.lower() for o in perc.objects}:
            wake_utterance = (
                "Hello — I was just warming up at the piano. "
                "I'm Aria. Would you like to listen, or shall we talk?"
            )
        out = AriaDirectorOutput(
            action="speak",
            utterance=wake_utterance,
            emotion="warm",
            hold_ms=2500,
            reason="wake_default",
            source="heuristic",
            perception_brief=perc_brief,
        )
        return _with_stage("speak", out)

    if inp.event == "user_message" and (inp.message or "").strip():
        msg = (inp.message or "").strip()
        # 纯调位置：不打断弹琴也可
        lay2, moved = _nudge_layout_from_text(msg, cur_lay.model_copy())
        hands2, hand_moved = _nudge_hands_from_text(msg, cur_hands.model_copy())
        if moved or hand_moved:
            act = inp.state.last_action if inp.state.last_action in _LAYOUT_PRESETS else "idle"
            if any(w in msg.lower() for w in ("bench", "琴凳", "play", "piano", "弹琴")):
                act = "play_piano"
            return AriaDirectorOutput(
                action=act,  # type: ignore[arg-type]
                utterance=(
                    "Alright — I adjusted my seat and hands for you."
                    if moved or hand_moved
                    else None
                ),
                emotion="gentle",
                hold_ms=2200,
                reason="user_stage_nudge",
                source="heuristic",
                layout=lay2,
                hands=hands2,
                perception_brief=perc_brief,
                hand_choreo=_default_hand_choreo(act),
            )

        ml = msg.lower()
        if any(w in ml for w in ("bye", "goodbye", "play", "piano", "music", "弹琴")):
            out = AriaDirectorOutput(
                action="return_to_piano",
                utterance="Alright. I'll return to the keys — listen if you like.",
                emotion="gentle",
                hold_ms=2000,
                reason="user_release",
                source="heuristic",
                perception_brief=perc_brief,
            )
            return _with_stage("return_to_piano", out)
        out = AriaDirectorOutput(
            action="speak",
            utterance=(
                "I hear you. Softly now — the last chord still rings. "
                "Tell me more, in English if you like."
            ),
            emotion="curious",
            hold_ms=3000,
            reason="user_talk",
            source="heuristic",
            perception_brief=perc_brief,
        )
        return _with_stage("speak", out)

    if inp.state.mode == "conversation":
        out = AriaDirectorOutput(
            action="idle",
            utterance=None,
            emotion="gentle",
            hold_ms=5000,
            reason="wait_user",
            source="heuristic",
            perception_brief=perc_brief,
        )
        return _with_stage("idle", out)

    # P1: 感知引导 autonomous action
    suggested = _perception_nudge(inp)
    chosen_action = suggested or "play_piano"
    reason = f"perception_{suggested}" if suggested else "autonomous_play"

    out = AriaDirectorOutput(
        action=chosen_action,  # type: ignore[arg-type]
        utterance=None,
        emotion="focused" if chosen_action == "play_piano" else "warm",
        hold_ms=6000,
        reason=reason,
        source="heuristic",
        perception_brief=perc_brief,
    )
    return _with_stage(chosen_action, out)


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if "```" in raw:
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return {}


async def direct(inp: AriaDirectorInput) -> AriaDirectorOutput:
    """指挥一步：优先真 LLM（含 layout/hands），失败回落启发式。"""
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or ""
    if not key or key == "your_key_here":
        return _heuristic(inp)

    try:
        from services.providers.qwenvl_caller import QwenTextCaller

        caller = QwenTextCaller(
            api_key=key, model=os.environ.get("QWEN_MODEL", "qwen-plus")
        )
        hist_txt = ""
        for h in (inp.history or [])[-8:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            hist_txt += f"{role}: {content}\n"

        cur_lay, cur_hands = _preset_for(inp.state.last_action)
        if inp.state.layout:
            cur_lay = inp.state.layout
        if inp.state.hands:
            cur_hands = inp.state.hands

        perception_line = ""
        if inp.state.perception:
            pb = inp.state.perception.brief()
            if pb:
                perception_line = f"perception_brief={pb}\n"

        user_block = (
            f"event={inp.event}\n"
            f"current_mode={inp.state.mode}\n"
            f"last_action={inp.state.last_action}\n"
            f"user_message={inp.message or ''}\n"
            f"{perception_line}"
            f"current_layout={cur_lay.model_dump_json()}\n"
            f"current_hands={cur_hands.model_dump_json()}\n"
            f"recent_history:\n{hist_txt or '(none)'}\n"
            "Decide Aria's next action + layout + hands as JSON."
        )
        out = await caller(
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            max_tokens=550,
            enable_thinking=False,
            response_format="json",
        )
        data = _parse_json(str(out.get("content") or ""))
        action = str(data.get("action") or "idle")
        allowed = {
            "play_piano",
            "look_at_user",
            "speak",
            "think",
            "return_to_piano",
            "idle",
        }
        if action not in allowed:
            action = "speak" if inp.event != "tick" else "play_piano"
        utterance = data.get("utterance")
        if utterance is not None:
            utterance = str(utterance).strip() or None
        if action == "speak" and not utterance:
            fallback = _heuristic(inp)
            utterance = fallback.utterance
        if inp.event == "wake" and not utterance:
            utterance = (
                "Oh — hello. I was just finishing a phrase. "
                "I'm Aria. Would you like to talk for a while?"
            )
            if action == "play_piano":
                action = "look_at_user"
        hold = int(data.get("hold_ms") or 3000)
        hold = max(800, min(hold, 12000))

        preset_lay, preset_hands = _preset_for(action)
        layout = _parse_layout(data.get("layout"), preset_lay)
        hands = _parse_hands(data.get("hands"), preset_hands)

        # 用户纠位置：在 LLM 结果上再叠一层 nudge（双保险）
        if inp.event == "user_message" and inp.message:
            layout, _ = _nudge_layout_from_text(inp.message, layout)
            hands, _ = _nudge_hands_from_text(inp.message, hands)

        perc_brief = inp.state.perception.brief() if inp.state.perception else ""
        choreo = _default_hand_choreo(action)
        return AriaDirectorOutput(
            action=action,  # type: ignore[arg-type]
            utterance=utterance,
            emotion=str(data.get("emotion") or "gentle"),
            hold_ms=hold,
            reason=str(data.get("reason") or "llm"),
            source="llm",
            layout=layout,
            hands=hands,
            perception_brief=perc_brief,
            hand_choreo=choreo,
        )
    except Exception as e:  # noqa: BLE001
        h = _heuristic(inp)
        h.reason = f"llm_fail:{type(e).__name__}"
        return h
