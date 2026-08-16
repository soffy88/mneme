"""P3: EchoMimic V2 Drive — oprim + service 层测试。

测试策略：
  - 侧车不可用时的降级（主要路径）
  - 请求/响应序列化
  - 缓存键计算
  - runtime_features 包含 echo_drive

不依赖真 GPU 侧车。
"""

from __future__ import annotations

import pytest

from services.aria_media import (
    EchoDriveInput,
    EchoDriveOutput,
    request_echo_drive,
    runtime_features,
)
from oprim.echo_drive import (
    EchoDriveResult,
    echo_available,
    echo_drive,
)


# ── oprim 层 ───────────────────────────────────────────────────────────────────


class TestEchoDriveResult:
    def test_ok_result(self):
        r = EchoDriveResult(
            ok=True,
            video_b64="aGVsbG8=",
            duration_ms=3000,
            cached=False,
        )
        assert r.ok
        assert r.video_b64 == "aGVsbG8="
        assert r.duration_ms == 3000

    def test_fail_result(self):
        r = EchoDriveResult(
            ok=False,
            backend="echomimic_unavailable",
            note="sidecar not reachable",
        )
        assert not r.ok
        assert "not reachable" in r.note

    def test_to_dict(self):
        r = EchoDriveResult(ok=True, video_b64="dGVzdA==", cached=True)
        d = r.to_dict()
        assert d["ok"] is True
        assert d["cached"] is True
        assert "video_b64" in d


class TestEchoDriveOprim:
    @pytest.mark.asyncio
    async def test_empty_audio_returns_fail(self):
        r = await echo_drive(audio_b64="")
        assert not r.ok
        assert "too small" in r.note

    @pytest.mark.asyncio
    async def test_short_audio_returns_fail(self):
        r = await echo_drive(audio_b64="abc")
        assert not r.ok

    @pytest.mark.asyncio
    async def test_unreachable_sidecar(self):
        """侧车不可达 → 优雅降级。"""
        r = await echo_drive(
            audio_b64="A" * 200,
            base_url="http://localhost:19999",  # 不存在
            timeout_s=2.0,
        )
        assert not r.ok
        assert "unavailable" in r.backend or "error" in r.backend

    @pytest.mark.asyncio
    async def test_echo_available_false_when_down(self):
        """健康检查：侧车不存在 → False。"""
        avail = await echo_available(base_url="http://localhost:19999")
        assert avail is False

    def test_cache_key_generation(self):
        """相同音频+hand_pose 生成相同缓存键。"""
        import hashlib

        audio = "A" * 200
        hand_pose = {"left_x_pct": 35.0, "pattern_label": "melody"}
        audio_hash = hashlib.sha256(audio.encode()).hexdigest()[:12]
        hand_hash = hashlib.sha256(str(hand_pose).encode()).hexdigest()[:8]
        expected = f"{audio_hash}_{hand_hash}"
        assert expected.startswith(audio_hash)
        assert hand_hash in expected


# ── Service 层 ────────────────────────────────────────────────────────────────


class TestEchoDriveService:
    @pytest.mark.asyncio
    async def test_no_env_url_degrades(self, monkeypatch: pytest.MonkeyPatch):
        """ECHO_BASE_URL 未配置 → degrade=true。"""
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)
        inp = EchoDriveInput(audio_b64="A" * 200)
        out = await request_echo_drive(inp)
        assert not out.ok
        assert out.degrade
        assert "not set" in out.note or "not configured" in out.note

    @pytest.mark.asyncio
    async def test_unreachable_url_degrades(self, monkeypatch: pytest.MonkeyPatch):
        """ECHO_BASE_URL 不可达 → degrade=true。"""
        monkeypatch.setenv("ECHO_BASE_URL", "http://localhost:19999")
        inp = EchoDriveInput(audio_b64="A" * 200)
        out = await request_echo_drive(inp)
        assert not out.ok
        assert out.degrade

    def test_short_audio_rejected_by_model(self):
        """音频太短 → pydantic 验证拒绝。"""
        with pytest.raises(Exception):
            EchoDriveInput(audio_b64="short")  # min_length=100

    def test_echo_drive_input_model(self):
        inp = EchoDriveInput(
            audio_b64="A" * 200,
            hand_pose={"pattern_label": "chord", "finger_spread": 0.85},
            emotion="warm",
        )
        assert inp.action == "play_piano"
        assert inp.hand_pose["pattern_label"] == "chord"

    def test_echo_drive_output_model(self):
        out = EchoDriveOutput(
            ok=True,
            video_b64="dmlkZW8=",
            duration_ms=5000,
            cached=True,
        )
        d = out.model_dump()
        assert d["ok"] is True
        assert d["cached"] is True
        assert d["degrade"] is False

    def test_echo_drive_output_degrade(self):
        out = EchoDriveOutput(
            ok=False,
            degrade=True,
            backend="echo_not_configured",
            note="fallback to P2",
        )
        assert out.degrade
        assert "P2" in out.note


# ── Runtime Features ──────────────────────────────────────────────────────────


class TestRuntimeFeaturesP3:
    def test_echo_drive_in_features(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ECHO_BASE_URL", "http://echomimic:8080")
        feats = runtime_features()
        assert "echo_drive" in feats
        assert feats["echo_drive"] is True
        assert "echo_degrade_to_p2" in feats
        assert feats["echo_degrade_to_p2"] is True

    def test_echo_drive_not_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)
        feats = runtime_features()
        assert feats["echo_drive"] is False
        # 降级策略始终可用
        assert feats["echo_degrade_to_p2"] is True

    def test_all_phases_present(self, monkeypatch: pytest.MonkeyPatch):
        """runtime_features 包含 P0-P3 所有特性。"""
        monkeypatch.delenv("ECHO_BASE_URL", raising=False)
        feats = runtime_features()
        # P0
        assert "director" in feats
        assert "cinema_layer" in feats
        assert "gsap_keys" in feats
        # P1
        assert "perception" in feats
        # P2
        assert "hand_choreo" in feats
        # P3
        assert "echo_drive" in feats
