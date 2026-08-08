"""Aria 数字人 Director（行为指挥层）。

3D VRM 渲染路径下，Director 只输出行为决策（action/utterance/emotion），
不再输出 CSS 布局或 GSAP 手部参数——骨骼动画由前端 AriaVRM.tsx 的
goalForPose() 内部处理。

LLM 输出：
  - action：行为指令（走/坐/弹/聊/想/闲）
  - utterance：说话内容（英文）
  - emotion：情绪标签
  - hold_ms：持续时间
"""

from __future__ import annotations

import json
import os
import random
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


DIRECTOR_SYSTEM = """You are the behavioral director for Aria, a 3D digital human pianist.
She exists in a warm music room with a grand piano. She can walk, sit, play piano, talk, think, and idle.

Available actions:
- play_piano: walk to the bench, sit, and play (default autonomous behavior)
- look_at_user: turn toward the camera / user
- speak: talk to the user (requires utterance)
- think: pause thoughtfully
- return_to_piano: walk back to the piano and resume playing
- idle: stand quietly with subtle breathing

Output ONLY valid JSON:
{
  "action": "play_piano|look_at_user|speak|think|return_to_piano|idle",
  "utterance": "English speech or null",
  "emotion": "focused|warm|gentle|curious|thoughtful",
  "hold_ms": 3000,
  "reason": "short note"
}

Behavioral guidelines:
- utterance in English when speaking. Never mention JSON/system.
- During autonomous ticks (event=tick), OCCASIONALLY choose "speak" with a short
  musical musing (1 sentence) instead of play_piano (~30-40% of the time).
  This makes Aria feel alive. Don't speak every tick.
- When the user says hello/wake, respond warmly and introduce yourself briefly.
- When the user says bye/play/piano, return to the piano gracefully.
- Keep utterances natural, poetic, brief (1-2 sentences max).

Scene perception (when provided):
- "perception_brief" describes what Aria sees (objects, lighting, mood, time).
- USE it to enrich utterances and choose fitting actions.
- If "grand_piano" is present, prefer play_piano over idle.
- If "evening" + "warm" lighting, a cozy utterance fits.
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
    perception_brief: str = ""


def _perception_nudge(inp: AriaDirectorInput) -> str | None:
    """P1: 基于场景感知建议 action。"""
    perc = inp.state.perception
    if perc is None:
        return None
    objs = {o.lower() for o in perc.objects}
    if objs & {"grand_piano", "upright_piano", "piano"}:
        return "play_piano"
    if objs & {"sheet_music", "music_stand"}:
        return "play_piano"
    if perc.mood in ("relaxed_conversation", "cozy_intimate"):
        return "speak"
    return None


_AUTO_UTTERANCES = [
    "This melody always makes me think of rainy afternoons.",
    "Hmm — let me try it a little slower this time.",
    "There's something about this chord progression… it just breathes.",
    "I could play this one all day, honestly.",
    "Listen — do you hear how the bass line answers the treble?",
    "Music is funny. Sometimes the pauses matter more than the notes.",
    "I wonder what you're thinking about right now.",
    "This piece reminds me of walking home after school.",
]


def _heuristic(inp: AriaDirectorInput) -> AriaDirectorOutput:
    """无 LLM 时的可演示行为。"""
    perc_brief = inp.state.perception.brief() if inp.state.perception else ""

    if inp.event == "wake":
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
        return AriaDirectorOutput(
            action="speak",
            utterance=wake_utterance,
            emotion="warm",
            hold_ms=2500,
            reason="wake_default",
            source="heuristic",
            perception_brief=perc_brief,
        )

    if inp.event == "user_message" and (inp.message or "").strip():
        msg = (inp.message or "").strip()
        ml = msg.lower()
        if any(w in ml for w in ("bye", "goodbye", "play", "piano", "music", "弹琴")):
            return AriaDirectorOutput(
                action="return_to_piano",
                utterance="Alright. I'll return to the keys — listen if you like.",
                emotion="gentle",
                hold_ms=2000,
                reason="user_release",
                source="heuristic",
                perception_brief=perc_brief,
            )
        return AriaDirectorOutput(
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

    if inp.state.mode == "conversation":
        return AriaDirectorOutput(
            action="idle",
            utterance=None,
            emotion="gentle",
            hold_ms=5000,
            reason="wait_user",
            source="heuristic",
            perception_brief=perc_brief,
        )

    # 自主 tick
    suggested = _perception_nudge(inp)
    chosen_action = suggested or "play_piano"
    reason = f"perception_{suggested}" if suggested else "autonomous_play"

    autonomous_utterance = None
    if inp.event == "tick" and inp.state.mode == "playing" and random.random() < 0.4:
        autonomous_utterance = random.choice(_AUTO_UTTERANCES)
        chosen_action = "speak"  # type: ignore[assignment]
        reason = "autonomous_speak"

    return AriaDirectorOutput(
        action=chosen_action,  # type: ignore[arg-type]
        utterance=autonomous_utterance,
        emotion="focused" if chosen_action == "play_piano" else "warm",
        hold_ms=6000 if not autonomous_utterance else 4000,
        reason=reason,
        source="heuristic",
        perception_brief=perc_brief,
    )


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
    """指挥一步：优先真 LLM，失败回落启发式。"""
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
            f"recent_history:\n{hist_txt or '(none)'}\n"
            "Decide Aria's next action as JSON."
        )
        out = await caller(
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            max_tokens=350,
            enable_thinking=False,
            response_format="json",
        )
        data = _parse_json(str(out.get("content") or ""))
        action = str(data.get("action") or "idle")
        allowed = {
            "play_piano", "look_at_user", "speak",
            "think", "return_to_piano", "idle",
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

        perc_brief = inp.state.perception.brief() if inp.state.perception else ""
        return AriaDirectorOutput(
            action=action,  # type: ignore[arg-type]
            utterance=utterance,
            emotion=str(data.get("emotion") or "gentle"),
            hold_ms=hold,
            reason=str(data.get("reason") or "llm"),
            source="llm",
            perception_brief=perc_brief,
        )
    except Exception as e:  # noqa: BLE001
        h = _heuristic(inp)
        h.reason = f"llm_fail:{type(e).__name__}"
        return h
