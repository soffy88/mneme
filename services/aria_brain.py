"""Aria Brain — 自主行为大脑（Phase 3）。

后端长驻 asyncio 循环，通过 WebSocket 向前端推送行为指令。
前端只是渲染器，被动接收指令执行。

架构（参考 Fay 大脑/身体分离）：
  Brain（本模块）
    ├── 状态机：idle → walking → sitting → playing → standing → talking
    ├── 事件队列：user_entered / user_spoke / silence_timeout / schedule_tick
    ├── LLM Director：给定状态+事件，规划下一个 action
    └── WebSocket 推送：action commands → 前端渲染器

不写掌握度。不调 process_interaction。仅 Aria 数字人行为。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BrainState(str, Enum):
    IDLE = "idle"
    WALKING = "walking"
    SITTING = "sitting"
    PLAYING = "playing"
    STANDING = "standing"
    TALKING = "talking"
    THINKING = "thinking"


@dataclass
class BrainEvent:
    kind: str  # user_entered | user_spoke | silence_timeout | tick | action_done
    text: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class BrainConfig:
    """Tunable parameters for the autonomous loop."""

    idle_tick_s: float = 8.0  # seconds between autonomous decisions when idle
    playing_duration_s: float = 25.0  # how long she plays before considering stopping
    silence_timeout_s: float = 15.0  # user silence → she might speak
    max_consecutive_play: int = 3  # don't play forever without variety


class AriaBrain:
    """Per-connection autonomous brain instance.

    One brain per WebSocket connection. Runs an asyncio loop that:
    1. Waits for events (user messages, timeouts, action completions)
    2. Decides next action via Director LLM (or heuristic)
    3. Pushes command to frontend via send callback
    """

    def __init__(
        self,
        student_id: str,
        send_fn: Any,  # async callable: (dict) -> None
        config: BrainConfig | None = None,
    ):
        self.student_id = student_id
        self._send = send_fn
        self.cfg = config or BrainConfig()
        self.state = BrainState.IDLE
        self._queue: asyncio.Queue[BrainEvent] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_user_ts = time.time()
        self._play_count = 0
        self._history: list[dict[str, str]] = []
        self._emotion = "gentle"

    async def start(self) -> None:
        """Start the brain loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        # Initial greeting after a short delay
        await self._queue_put(BrainEvent(kind="tick"))

    async def stop(self) -> None:
        """Stop the brain loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def push_event(self, kind: str, text: str = "") -> None:
        """External event from frontend (user spoke, entered, etc.)."""
        if kind in ("user_spoke", "user_entered"):
            self._last_user_ts = time.time()
        await self._queue_put(BrainEvent(kind=kind, text=text))

    async def _queue_put(self, ev: BrainEvent) -> None:
        await self._queue.put(ev)

    async def _loop(self) -> None:
        """Main brain loop: wait for events, decide, push commands."""
        while self._running:
            try:
                # Wait for next event with timeout (autonomous tick)
                try:
                    ev = await asyncio.wait_for(
                        self._queue.get(), timeout=self.cfg.idle_tick_s
                    )
                except asyncio.TimeoutError:
                    ev = BrainEvent(kind="silence_timeout")

                cmd = await self._decide(ev)
                if cmd:
                    await self._send(cmd)
                    # Wait for action to "complete" (hold_ms)
                    hold = cmd.get("hold_ms", 3000)
                    await asyncio.sleep(hold / 1000)
                    # Notify self that action is done
                    await self._queue_put(BrainEvent(kind="action_done"))

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[AriaBrain] loop error")
                await asyncio.sleep(2)

    async def _decide(self, ev: BrainEvent) -> dict[str, Any] | None:
        """Decide next action based on event and current state."""
        # User spoke → respond conversationally
        if ev.kind == "user_spoke" and ev.text.strip():
            self._history.append({"role": "user", "content": ev.text.strip()})
            cmd = await self._director_call("user_message", ev.text.strip())
            if cmd:
                self.state = BrainState.TALKING
                self._history.append({"role": "assistant", "content": cmd.get("utterance", "")})
            return cmd

        # User entered → greet
        if ev.kind == "user_entered":
            self.state = BrainState.TALKING
            return {
                "action": "look_at_user",
                "utterance": "Oh, hello! I didn't hear you come in. Would you like to hear something?",
                "emotion": "happy",
                "hold_ms": 4000,
                "source": "brain_greeting",
            }

        # Action done → transition state
        if ev.kind == "action_done":
            if self.state == BrainState.TALKING:
                # After talking, maybe return to piano
                silence = time.time() - self._last_user_ts
                if silence > self.cfg.silence_timeout_s:
                    self.state = BrainState.IDLE
                    return {
                        "action": "return_to_piano",
                        "utterance": "",
                        "emotion": "focused",
                        "hold_ms": 2000,
                        "source": "brain_return",
                    }
            elif self.state == BrainState.PLAYING:
                self._play_count += 1
                if self._play_count >= self.cfg.max_consecutive_play:
                    self._play_count = 0
                    self.state = BrainState.IDLE
                    return {
                        "action": "look_at_user",
                        "utterance": "That was a lovely piece. I think I'll rest my fingers for a moment.",
                        "emotion": "relaxed",
                        "hold_ms": 5000,
                        "source": "brain_rest",
                    }
            return None

        # Silence timeout → autonomous behavior
        if ev.kind in ("silence_timeout", "tick"):
            silence = time.time() - self._last_user_ts

            # If user was recently active, don't interrupt
            if silence < self.cfg.silence_timeout_s and ev.kind == "silence_timeout":
                return None

            # Decide autonomously via Director
            cmd = await self._director_call("tick", "")
            if cmd:
                action = cmd.get("action", "idle")
                if action in ("play_piano", "return_to_piano"):
                    self.state = BrainState.PLAYING
                elif action in ("speak", "look_at_user"):
                    self.state = BrainState.TALKING
                elif action == "think":
                    self.state = BrainState.THINKING
                else:
                    self.state = BrainState.IDLE
            return cmd

        return None

    async def _director_call(self, event: str, message: str) -> dict[str, Any] | None:
        """Call the Director LLM for a behavioral decision."""
        try:
            from services.aria_director import AriaDirectorInput, AriaDirectorState, direct

            inp = AriaDirectorInput(
                event=event,  # type: ignore[arg-type]
                message=message or None,
                history=self._history[-10:],
                state=AriaDirectorState(
                    mode=(
                        "playing"
                        if self.state == BrainState.PLAYING
                        else "conversation"
                    ),
                    last_action=self.state.value,
                    emotion=self._emotion,
                ),
            )
            out = await direct(inp)
            self._emotion = out.emotion
            return {
                "action": out.action,
                "utterance": out.utterance,
                "emotion": out.emotion,
                "hold_ms": out.hold_ms,
                "source": out.source,
            }
        except Exception:
            logger.warning("[AriaBrain] director call failed, using heuristic")
            return self._heuristic_fallback(event)

    def _heuristic_fallback(self, event: str) -> dict[str, Any] | None:
        """Simple heuristic when LLM is unavailable."""
        if self.state == BrainState.PLAYING:
            return None  # keep playing
        if event == "tick":
            self.state = BrainState.PLAYING
            return {
                "action": "play_piano",
                "utterance": "",
                "emotion": "focused",
                "hold_ms": 20000,
                "source": "brain_heuristic",
            }
        return {
            "action": "idle",
            "utterance": "",
            "emotion": "gentle",
            "hold_ms": 5000,
            "source": "brain_heuristic",
        }
