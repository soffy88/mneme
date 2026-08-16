"""Aria Media Planner + Lipsync + TTS + EchoMimic Drive（Phase 1–3 / P3）.

- 不写掌握度 / 不调 process_interaction。
- Clip 池：静图轮播（/aria/clips/playing_*.jpg）+ 可选 mp4 / env URL。
- Lipsync：ARIA_LIPSYNC_BASE_URL 侧车或 viseme_css。
- TTS：edge-tts en-US-AriaNeural（免费云），失败由前端 Web Speech 兜底。
- EchoMimic：ECHO_BASE_URL 侧车（音频→半身驱动视频），不可用则降级到 P2 模拟。
"""

from __future__ import annotations

import base64
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

LipsyncMode = Literal["video", "viseme_css", "none"]

# 前端 public 路径（mneme-web）；API 只返回 URL，不托管静态文件
_DEFAULT_PLAYING_STILLS = [
    "/aria/clips/playing_00.jpg",
    "/aria/clips/playing_01.jpg",
    "/aria/clips/playing_02.jpg",
]
_DEFAULT_PLAYING = "/aria/playing.jpg"
_DEFAULT_TALK = "/aria/conversation.jpg"


class LipsyncInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    emotion: str = "warm"
    still_hint: str | None = None


class LipsyncOutput(BaseModel):
    ok: bool = True
    mode: LipsyncMode = "viseme_css"
    video_url: str | None = None
    still_url: str = _DEFAULT_TALK
    duration_ms: int = 3000
    backend: str = "fallback"
    note: str = ""


class MediaPlan(BaseModel):
    action: str
    still_url: str
    still_pool: list[str] = Field(default_factory=list)
    clip_url: str | None = None
    keys_overlay: bool = False
    rotate_ms: int = 0
    note: str = ""


class TtsInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str | None = None


class VisemeCue(BaseModel):
    """Single viseme cue: mouth shape at a point in time."""

    t: float = Field(..., description="offset in seconds from audio start")
    d: float = Field(..., description="duration in seconds")
    v: str = Field(..., description="viseme id: aa|ih|ou|ee|oh|sil")


class TtsOutput(BaseModel):
    ok: bool = True
    audio_b64: str | None = None
    mime: str = "audio/mpeg"
    backend: str = "none"
    voice: str | None = None
    note: str = ""
    visemes: list[VisemeCue] = Field(default_factory=list)


def _clip_mp4_url() -> str | None:
    """仅当显式配置时才用「人像驱动」视频。

    禁止默认 Ken Burns 整图晃动（房间背景会被带着动）。
    正确路径：EchoMimic/Omni 输出的半身驱动片，或抠像人像层。
    """
    env = (os.environ.get("ARIA_CLIP_PLAYING_URL") or "").strip()
    return env or None


def _talk_clip_url() -> str | None:
    env = (os.environ.get("ARIA_CLIP_TALK_URL") or "").strip()
    return env or None


def plan_media(action: str) -> MediaPlan:
    """按 Director action 选静图 / 可选人像驱动 clip（非整图运镜）。"""
    a = (action or "idle").strip()
    if a in ("play_piano", "return_to_piano"):
        # 主视觉：稳定全景写真（房间不动）；不轮播晃图
        return MediaPlan(
            action=a,
            still_url=_DEFAULT_PLAYING,
            still_pool=[_DEFAULT_PLAYING],
            clip_url=_clip_mp4_url(),
            keys_overlay=True,
            rotate_ms=0,
            note=(
                "stable photoreal still (room fixed); "
                "set ARIA_CLIP_PLAYING_URL to EchoMimic-driven person clip only"
            ),
        )
    if a in ("speak", "look_at_user", "think", "idle"):
        return MediaPlan(
            action=a,
            still_url=_DEFAULT_TALK,
            still_pool=[_DEFAULT_TALK],
            clip_url=_talk_clip_url(),
            keys_overlay=False,
            rotate_ms=0,
            note=(
                "stable conversation still; "
                "set ARIA_CLIP_TALK_URL or lipsync sidecar for person-only motion"
            ),
        )
    return MediaPlan(
        action=a,
        still_url=_DEFAULT_PLAYING,
        still_pool=[_DEFAULT_PLAYING],
        keys_overlay=False,
        note="default still",
    )


def _estimate_duration_ms(text: str) -> int:
    n = max(1, len(text.strip()))
    return int(min(20000, max(1800, 1600 + n * 55)))


async def lipsync(inp: LipsyncInput) -> LipsyncOutput:
    """请求口型视频；侧车不可用则 CSS viseme fallback。"""
    text = inp.text.strip()
    still = inp.still_hint or _DEFAULT_TALK
    duration = _estimate_duration_ms(text)
    base = (os.environ.get("ARIA_LIPSYNC_BASE_URL") or "").rstrip("/")

    if not base:
        return LipsyncOutput(
            ok=True,
            mode="viseme_css",
            video_url=None,
            still_url=still,
            duration_ms=duration,
            backend="fallback",
            note="Set ARIA_LIPSYNC_BASE_URL for LivePortrait/EchoMimic GPU sidecar.",
        )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{base}/v1/lipsync",
                json={
                    "text": text,
                    "emotion": inp.emotion,
                    "still_url": still,
                },
            )
            if r.status_code >= 400:
                return LipsyncOutput(
                    ok=True,
                    mode="viseme_css",
                    still_url=still,
                    duration_ms=duration,
                    backend="sidecar_error",
                    note=f"sidecar HTTP {r.status_code}; using viseme_css",
                )
            data: dict[str, Any] = r.json()
            video = data.get("video_url") or data.get("stream_url")
            if video:
                return LipsyncOutput(
                    ok=True,
                    mode="video",
                    video_url=str(video),
                    still_url=still,
                    duration_ms=int(data.get("duration_ms") or duration),
                    backend="sidecar",
                    note="GPU lipsync video",
                )
            return LipsyncOutput(
                ok=True,
                mode="viseme_css",
                still_url=still,
                duration_ms=duration,
                backend="sidecar_empty",
                note="sidecar returned no video_url",
            )
    except Exception as e:  # noqa: BLE001
        return LipsyncOutput(
            ok=True,
            mode="viseme_css",
            still_url=still,
            duration_ms=duration,
            backend="sidecar_exception",
            note=f"{type(e).__name__}: fallback viseme_css",
        )


def _word_to_viseme(word: str) -> str:
    """Heuristic English word → dominant VRM viseme (aa/ih/ou/ee/oh)."""
    w = word.lower().strip(".,!?;:'\"-")
    if not w:
        return "sil"
    # Check dominant vowel pattern
    if any(c in w for c in "ou") and not any(c in w for c in "ei"):
        return "ou"
    if "oo" in w or w.endswith("u"):
        return "ou"
    if any(c in w for c in "ee") or w.endswith("e") or "i" in w:
        return "ee"
    if "a" in w:
        return "aa"
    return "ih"


_TICKS_PER_SEC = 10_000_000  # edge-tts offsets are in 100ns ticks


def _build_viseme_timeline(
    boundaries: list[dict[str, Any]],
) -> list[VisemeCue]:
    """Convert edge-tts WordBoundary events to viseme cues.

    Each word gets: onset (ih, 30ms) → vowel (viseme, word_dur-60ms) → offset (sil, 30ms).
    Offsets from edge-tts are in 100-nanosecond ticks; we convert to seconds.
    """
    cues: list[VisemeCue] = []
    for wb in boundaries:
        offset = float(wb.get("offset", 0)) / _TICKS_PER_SEC
        dur = float(wb.get("duration", 1_000_000)) / _TICKS_PER_SEC
        text = str(wb.get("text", ""))
        vis = _word_to_viseme(text)
        # onset: brief closed→open transition
        onset_d = min(0.03, dur * 0.2)
        cues.append(VisemeCue(t=round(offset, 4), d=round(onset_d, 4), v="ih"))
        # main vowel shape
        main_d = max(0.02, dur - 0.06)
        cues.append(VisemeCue(t=round(offset + onset_d, 4), d=round(main_d, 4), v=vis))
        # offset: brief closure
        cues.append(VisemeCue(t=round(offset + dur - 0.03, 4), d=0.03, v="sil"))
    return cues


async def synthesize_tts(inp: TtsInput) -> TtsOutput:
    """英文 TTS：edge-tts AriaNeural streaming + viseme timeline。

    使用 stream() 收集音频分片和 WordBoundary 事件，
    返回 audio_b64 + visemes（前端驱动 VRM 口型 blendshape）。
    """
    text = inp.text.strip()
    voice = (inp.voice or os.environ.get("ARIA_TTS_VOICE") or "en-US-AriaNeural").strip()
    try:
        import edge_tts  # type: ignore
    except ImportError:
        return TtsOutput(
            ok=False,
            backend="missing_edge_tts",
            note="pip install edge-tts; frontend will use Web Speech",
        )

    try:
        communicate = edge_tts.Communicate(
            text, voice, rate="-5%", boundary="WordBoundary"
        )
        audio_chunks: list[bytes] = []
        boundaries: list[dict[str, Any]] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append({
                    "offset": chunk.get("offset", 0),
                    "duration": chunk.get("duration", 0.1),
                    "text": chunk.get("text", ""),
                })

        raw = b"".join(audio_chunks)
        if len(raw) < 64:
            return TtsOutput(ok=False, backend="edge_tts_empty", note="empty audio")

        visemes = _build_viseme_timeline(boundaries)
        return TtsOutput(
            ok=True,
            audio_b64=base64.b64encode(raw).decode("ascii"),
            mime="audio/mpeg",
            backend="edge_tts",
            voice=voice,
            visemes=visemes,
            note=f"edge-tts stream + {len(visemes)} viseme cues",
        )
    except Exception as e:  # noqa: BLE001
        return TtsOutput(
            ok=False,
            backend="edge_tts_error",
            voice=voice,
            note=f"{type(e).__name__}: {e}",
        )


def runtime_features() -> dict[str, Any]:
    echo = bool((os.environ.get("ECHO_BASE_URL") or "").strip())
    try:
        import edge_tts  # noqa: F401

        tts_ok = True
    except ImportError:
        tts_ok = False
    return {
        "director": True,
        "autonomous_tick": True,
        "tts_edge": tts_ok,
        "perception": True,
        "echo_drive": echo,
        "echo_degrade_to_p2": True,
    }


# ── P3: EchoMimic Drive ───────────────────────────────────────────────────────


class EchoDriveInput(BaseModel):
    """EchoMimic 驱动请求（服务层入口）。"""

    audio_b64: str = Field(..., min_length=100, description="音频 base64")
    hand_pose: dict[str, Any] | None = Field(None, description="P2 HandChoreoParams")
    emotion: str = "neutral"
    action: str = "play_piano"


class EchoDriveOutput(BaseModel):
    """EchoMimic 驱动结果（服务层出口）。"""

    ok: bool = True
    video_b64: str | None = None
    video_url: str | None = None
    duration_ms: int = 0
    cached: bool = False
    backend: str = "echomimic_v2"
    degrade: bool = False
    note: str = ""


async def request_echo_drive(inp: EchoDriveInput) -> EchoDriveOutput:
    """调用 EchoMimic V2 侧车；不可用则 degrade（前端回退 P2）。"""
    echo_url = (os.environ.get("ECHO_BASE_URL") or "").strip()
    if not echo_url:
        return EchoDriveOutput(
            ok=False,
            degrade=True,
            backend="echo_not_configured",
            note="ECHO_BASE_URL not set; frontend uses P2 simulated hands",
        )

    try:
        from oprim.echo_drive import echo_drive

        result = await echo_drive(
            audio_b64=inp.audio_b64,
            hand_pose=inp.hand_pose,
            emotion=inp.emotion,
            base_url=echo_url,
        )
        return EchoDriveOutput(
            ok=result.ok,
            video_b64=result.video_b64,
            video_url=result.video_url,
            duration_ms=result.duration_ms,
            cached=result.cached,
            backend=result.backend,
            degrade=not result.ok,
            note=result.note,
        )
    except Exception as e:  # noqa: BLE001
        return EchoDriveOutput(
            ok=False,
            degrade=True,
            backend="echo_exception",
            note=f"{type(e).__name__}: frontend uses P2 fallback",
        )
