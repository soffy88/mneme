"""mneme-speech 客户端 + TTS 音频缓存（MinIO bucket ``tts-audio``，按文本哈希）。

TTS/ASR 都在自托管 sherpa-onnx 容器（``SPEECH_BASE_URL``，默认 http://speech:8080，仅内网）。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from typing import Any, AsyncIterator, Optional, Protocol

import httpx

from services.speech_text import tts_ready

BUCKET = os.environ.get("TTS_BUCKET", "tts-audio")
VOICE = "matcha-zh-baker-v1"


def base_url() -> str:
    return os.environ.get("SPEECH_BASE_URL", "http://speech:8080").rstrip("/")


def cache_key(spoken: str, speed: float = 1.0) -> str:
    h = hashlib.sha256(f"{VOICE}|{speed:.2f}|{spoken}".encode("utf-8")).hexdigest()
    return f"{VOICE}/{h[:2]}/{h}.wav"


class AudioStore(Protocol):
    def get(self, key: str) -> Optional[bytes]: ...
    def put(self, key: str, data: bytes) -> None: ...


class MinioAudioStore:
    def _c(self) -> Any:
        from services.storage import _client

        c = _client()
        if not c.bucket_exists(BUCKET):
            c.make_bucket(BUCKET)
        return c

    def get(self, key: str) -> Optional[bytes]:
        from minio.error import S3Error

        try:
            resp = self._c().get_object(BUCKET, key)
            try:
                return bytes(resp.read())
            finally:
                resp.close()
                resp.release_conn()
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                return None
            raise

    def put(self, key: str, data: bytes) -> None:
        self._c().put_object(BUCKET, key, io.BytesIO(data), length=len(data), content_type="audio/wav")


class SpeechError(RuntimeError):
    pass


class SpeechClient:
    """HTTP/WS 访问 mneme-speech。测试中整体替换为 fake。"""

    def __init__(self, store: Optional[AudioStore] = None, timeout: float = 30.0):
        self.store: AudioStore = store or MinioAudioStore()
        self.timeout = timeout

    async def synth_raw(self, spoken: str, speed: float = 1.0) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{base_url()}/tts", json={"text": spoken, "speed": speed})
        if r.status_code != 200:
            raise SpeechError(f"tts {r.status_code}")
        return r.content

    async def tts(self, text: str, *, speed: float = 1.0, already_spoken: bool = False) -> tuple[bytes, str, bool]:
        """返回 (wav, 规整后的朗读文本, 是否命中缓存)。"""
        spoken = text if already_spoken else tts_ready(text)
        if not spoken:
            raise SpeechError("empty")
        key = cache_key(spoken, speed)
        try:
            hit = await asyncio.to_thread(self.store.get, key)
        except Exception:  # noqa: BLE001 - cache is best-effort
            hit = None
        if hit:
            return hit, spoken, True
        wav = await self.synth_raw(spoken, speed)
        try:
            await asyncio.to_thread(self.store.put, key, wav)
        except Exception:  # noqa: BLE001 - cache is best-effort
            pass
        return wav, spoken, False

    async def asr(self, pcm16: bytes) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{base_url()}/asr", content=pcm16)
        if r.status_code != 200:
            raise SpeechError(f"asr {r.status_code}")
        return str(r.json().get("text", ""))

    def open_stream(self) -> "AsrStream":
        return WsAsrStream(base_url().replace("http", "ws", 1) + "/stream")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                return (await c.get(f"{base_url()}/health")).status_code == 200
        except Exception:  # noqa: BLE001
            return False


class AsrStream(Protocol):
    async def connect(self) -> None: ...
    async def send(self, pcm16: bytes) -> None: ...
    async def flush(self) -> None: ...
    def events(self) -> AsyncIterator[dict]: ...
    async def close(self) -> None: ...


class WsAsrStream:
    def __init__(self, url: str):
        self.url = url
        self.ws: Any = None

    async def connect(self) -> None:
        import websockets

        self.ws = await websockets.connect(self.url, max_size=2**22, open_timeout=10)

    async def send(self, pcm16: bytes) -> None:
        await self.ws.send(pcm16)

    async def flush(self) -> None:
        await self.ws.send(json.dumps({"type": "flush"}))

    async def events(self) -> AsyncIterator[dict]:
        async for msg in self.ws:
            if isinstance(msg, str):
                try:
                    yield json.loads(msg)
                except ValueError:
                    continue

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()


_client_singleton: Optional[SpeechClient] = None


def get_speech_client() -> SpeechClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = SpeechClient()
    return _client_singleton
