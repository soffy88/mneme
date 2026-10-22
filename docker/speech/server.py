"""mneme-speech：自托管中文语音服务（sherpa-onnx，纯 CPU，国内可用）。

- POST /tts   {text, speed?}            → audio/wav（matcha-icefall-zh-baker + vocos）
- POST /asr   body=PCM16LE 16kHz mono    → {text}（SenseVoice int8）
- WS   /stream 二进制 PCM16LE 16kHz 帧    → {"type":"speech_start"} / {"type":"final","text"}
               文本帧 {"type":"flush"} 结束当前话段
- GET  /health

只做语音 I/O，不碰学习数据；不对公网暴露（仅 compose 内网，由 mneme-api 代理并鉴权）。
设计参考 Open-LLM-VTuber 的 VAD→ASR 管线（未复制其代码）。
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
import wave

import numpy as np
import sherpa_onnx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

M = os.environ.get("SPEECH_MODEL_DIR", "/models")
THREADS = int(os.environ.get("SPEECH_THREADS", "2"))
ASR_DIR = os.environ.get("ASR_DIR", f"{M}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09")
TTS_DIR = os.environ.get("TTS_DIR", f"{M}/matcha-icefall-zh-baker")
VOCODER = os.environ.get("TTS_VOCODER", f"{M}/vocos-22khz-univ.onnx")
VAD_MODEL = os.environ.get("VAD_MODEL", f"{M}/silero_vad.onnx")
SR = 16000
MAX_TTS_CHARS = 800

app = FastAPI(title="mneme-speech")
_tts_lock = threading.Lock()
_asr_lock = threading.Lock()


def _first(d: str, *names: str) -> str:
    for n in names:
        p = os.path.join(d, n)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{d}: none of {names}")


def _load_tts() -> sherpa_onnx.OfflineTts:
    fsts = ",".join(
        os.path.join(TTS_DIR, f) for f in ("phone.fst", "date.fst", "number.fst")
        if os.path.exists(os.path.join(TTS_DIR, f))
    )
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=_first(TTS_DIR, "model-steps-3.onnx", "model-steps-2.onnx"),
                vocoder=VOCODER,
                lexicon=os.path.join(TTS_DIR, "lexicon.txt"),
                tokens=os.path.join(TTS_DIR, "tokens.txt"),
                dict_dir=os.path.join(TTS_DIR, "dict"),
            ),
            num_threads=THREADS,
            provider="cpu",
        ),
        rule_fsts=fsts,
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def _load_asr() -> sherpa_onnx.OfflineRecognizer:
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=_first(ASR_DIR, "model.int8.onnx", "model.onnx"),
        tokens=os.path.join(ASR_DIR, "tokens.txt"),
        num_threads=THREADS,
        use_itn=True,
        language="zh",
    )


def _vad_config() -> sherpa_onnx.VadModelConfig:
    c = sherpa_onnx.VadModelConfig()
    c.silero_vad.model = VAD_MODEL
    c.silero_vad.threshold = 0.5
    c.silero_vad.min_silence_duration = 0.6
    c.silero_vad.min_speech_duration = 0.25
    c.silero_vad.max_speech_duration = 20
    c.sample_rate = SR
    c.num_threads = 1
    return c


TTS = _load_tts()
ASR = _load_asr()


def _wav(samples: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def _synth(text: str, speed: float) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    with _tts_lock:
        a = TTS.generate(text, sid=0, speed=speed)
    return _wav(np.asarray(a.samples, dtype=np.float32), a.sample_rate), time.perf_counter() - t0


def _recognize(samples: np.ndarray) -> str:
    with _asr_lock:
        s = ASR.create_stream()
        s.accept_waveform(SR, samples)
        ASR.decode_stream(s)
        return s.result.text.strip()


def _pcm_to_f32(b: bytes) -> np.ndarray:
    if len(b) % 2:
        b = b[:-1]
    return np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "tts_sample_rate": TTS.sample_rate, "threads": THREADS}


@app.post("/tts")
async def tts(req: Request) -> Response:
    body = await req.json()
    text = str(body.get("text") or "").strip()[:MAX_TTS_CHARS]
    if not text:
        raise HTTPException(400, "empty text")
    speed = float(body.get("speed") or 1.0)
    speed = min(max(speed, 0.6), 1.6)
    wav, secs = await asyncio.to_thread(_synth, text, speed)
    return Response(wav, media_type="audio/wav", headers={"X-Synth-Seconds": f"{secs:.3f}"})


@app.post("/asr")
async def asr(req: Request) -> JSONResponse:
    raw = await req.body()
    if len(raw) > SR * 2 * 60:
        raise HTTPException(413, "audio too long (max 60s)")
    t0 = time.perf_counter()
    text = await asyncio.to_thread(_recognize, _pcm_to_f32(raw))
    return JSONResponse({"text": text, "seconds": round(time.perf_counter() - t0, 3)})


@app.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    vad = sherpa_onnx.VoiceActivityDetector(_vad_config(), buffer_size_in_seconds=60)
    win = 512
    pending = np.zeros(0, dtype=np.float32)
    in_speech = False

    async def drain() -> None:
        while not vad.empty():
            seg = np.asarray(vad.front.samples, dtype=np.float32)
            vad.pop()
            t0 = time.perf_counter()
            text = await asyncio.to_thread(_recognize, seg)
            await ws.send_text(json.dumps({
                "type": "final", "text": text,
                "audio_seconds": round(len(seg) / SR, 2),
                "asr_seconds": round(time.perf_counter() - t0, 3),
            }, ensure_ascii=False))

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                pending = np.concatenate([pending, _pcm_to_f32(msg["bytes"])])
                n = (len(pending) // win) * win
                if n:
                    vad.accept_waveform(pending[:n])
                    pending = pending[n:]
                speaking = vad.is_speech_detected()
                if speaking and not in_speech:
                    await ws.send_text(json.dumps({"type": "speech_start"}))
                in_speech = speaking
                await drain()
            elif msg.get("text"):
                try:
                    cmd = json.loads(msg["text"])
                except ValueError:
                    continue
                if cmd.get("type") == "flush":
                    if len(pending):
                        vad.accept_waveform(np.concatenate([pending, np.zeros(win - len(pending) % win, dtype=np.float32)]))
                        pending = np.zeros(0, dtype=np.float32)
                    vad.flush()
                    in_speech = False
                    await drain()
                    vad.reset()
                    await ws.send_text(json.dumps({"type": "flushed"}))
    except WebSocketDisconnect:
        pass
