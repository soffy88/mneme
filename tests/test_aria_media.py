"""Aria Media Planner / Lipsync / TTS 单元测试。"""

from __future__ import annotations

import pytest

from services.aria_media import (
    LipsyncInput,
    TtsInput,
    TtsOutput,
    VisemeCue,
    _build_viseme_timeline,
    _word_to_viseme,
    lipsync,
    plan_media,
    runtime_features,
    synthesize_tts,
)


def test_plan_media_piano_stable_still(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ARIA_CLIP_PLAYING_URL", raising=False)
    p = plan_media("play_piano")
    assert p.keys_overlay is True
    assert p.rotate_ms == 0
    assert p.clip_url is None  # 默认禁止 Ken Burns 整图视频
    assert "playing" in p.still_url


def test_plan_media_speak_stable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ARIA_CLIP_TALK_URL", raising=False)
    p = plan_media("speak")
    assert "conversation" in p.still_url
    assert p.keys_overlay is False
    assert p.clip_url is None


def test_plan_media_piano_explicit_person_clip(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARIA_CLIP_PLAYING_URL", "/aria/clips/person_driven.mp4")
    p = plan_media("play_piano")
    assert p.clip_url == "/aria/clips/person_driven.mp4"


@pytest.mark.asyncio
async def test_lipsync_fallback_without_sidecar(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ARIA_LIPSYNC_BASE_URL", raising=False)
    out = await lipsync(LipsyncInput(text="Hello Aria, soft as moonlight."))
    assert out.ok is True
    assert out.mode == "viseme_css"
    assert out.video_url is None
    assert out.duration_ms >= 1800


@pytest.mark.asyncio
async def test_tts_edge_or_graceful():
    out = await synthesize_tts(TtsInput(text="Hello, I am Aria at the piano."))
    # edge-tts 可能未装；装了则应有 audio
    if out.ok:
        assert out.audio_b64 and len(out.audio_b64) > 100
        assert out.backend == "edge_tts"
    else:
        assert out.backend in ("missing_edge_tts", "edge_tts_error", "edge_tts_empty")


def test_runtime_features_shape():
    f = runtime_features()
    assert f["director"] is True
    assert f["autonomous_tick"] is True
    assert "tts_edge" in f


# ── viseme 纯函数（edge-tts 缺失路径也可直接测）──────────────────────────────


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("you", "ou"),
        ("how", "ou"),
        ("soon", "ou"),
        ("fine", "ee"),
        ("we", "ee"),
        ("cat", "aa"),
        ("", "sil"),
        ("cry", "ih"),
        ("Hello,", "ee"),  # 标点剥离后按含 'e' 判为 ee
    ],
)
def test_word_to_viseme(word, expected):
    assert _word_to_viseme(word) == expected


def test_build_viseme_timeline_shape():
    boundaries = [{"offset": 0, "duration": 5_000_000, "text": "cat"}]
    cues = _build_viseme_timeline(boundaries)
    assert len(cues) == 3  # onset(ih) → vowel → offset(sil)
    assert cues[0].v == "ih"
    assert cues[0].d == 0.03
    assert cues[1].v == "aa"
    assert round(cues[1].d, 2) == 0.44  # 0.5 - 0.06
    assert cues[2].v == "sil"
    assert cues[0].t == 0.0
    assert round(cues[2].t, 2) == 0.47  # offset 从秒换算


def test_build_viseme_timeline_converts_ticks_to_seconds():
    boundaries = [{"offset": 10_000_000, "duration": 20_000_000, "text": "you"}]
    cues = _build_viseme_timeline(boundaries)
    assert cues[0].t == 1.0  # 10_000_000 ticks = 1s
    assert cues[1].v == "ou"


def test_tts_output_and_viseme_models():
    v = VisemeCue(t=1.0, d=0.1, v="aa")
    out = TtsOutput(ok=True, backend="edge_tts", visemes=[v])
    assert out.visemes[0].v == "aa"
    assert out.mime == "audio/mpeg"
    assert TtsOutput(ok=False, backend="missing_edge_tts").visemes == []
