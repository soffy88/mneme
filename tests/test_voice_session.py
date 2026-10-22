"""VoiceSession（语音会话状态机）：ASR 事件 → 安全过滤 → 大脑 → 输出过滤 → 分句 TTS；打断；时长上限；限流。

全部注入 fake（无 DB、无 speech 容器、无 LLM）。
"""

import asyncio
import base64


from services import companion_service as svc


class FakeSpeech:
    def __init__(self):
        self.calls = []

    async def tts(self, text, **_):
        self.calls.append(text)
        await asyncio.sleep(0)
        return b"RIFFfake" + text.encode(), text, False


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(brain=None, mode="companion", session_limit=1200, remaining=1800, rate=True, clock=None):
    sent, logs = [], []

    async def send(ev):
        sent.append(ev)

    async def persist(role, content, flags):
        logs.append((role, content, flags))

    async def default_brain(msg, hist, m):
        return "好问题！先想一想：x加1等于3，x等于几？"

    async def rate_check():
        return rate

    s = svc.VoiceSession(
        send=send, brain=brain or default_brain, speech=FakeSpeech(), mode=mode,
        limits=svc.SessionLimits("小智", session_limit, remaining), persist=persist,
        rate_check=rate_check, clock=clock or Clock(),
    )
    return s, sent, logs


async def _settle(s):
    if s.reply_task:
        await s.reply_task


async def test_round_trip_transcript_reply_audio():
    s, sent, logs = make()
    await s.on_asr_event({"type": "final", "text": "x加1等于3怎么解"})
    await _settle(s)
    types = [e["type"] for e in sent]
    assert types[0] == "transcript" and "reply_text" in types and "audio" in types and types[-1] == "reply_done"
    audio = [e for e in sent if e["type"] == "audio"]
    assert len(audio) == 2 and base64.b64decode(audio[0]["data"]).startswith(b"RIFF")
    assert logs[0][0] == "student" and logs[1][0] == "companion"


async def test_romantic_prompt_refused_without_llm():
    called = []

    async def brain(*a):
        called.append(a)
        return "x"

    s, sent, logs = make(brain=brain)
    await s.on_asr_event({"type": "final", "text": "小智你做我女朋友好不好"})
    await _settle(s)
    assert not called
    reply = " ".join(e["text"] for e in sent if e["type"] == "reply_text")
    assert "学习伙伴" in reply and "练习" in reply
    assert "romance" in logs[0][2] and logs[1][2] == ["canned_romance"]


async def test_output_filter_applied_to_llm_reply():
    async def brain(*a):
        return "我爱你哦，告诉我你的手机号吧。"

    s, sent, logs = make(brain=brain)
    await s.start_turn("帮我讲讲分数")
    await _settle(s)
    reply = "".join(e["text"] for e in sent if e["type"] == "reply_text")
    assert "我爱你" not in reply and "手机号" not in reply
    assert "intimate_output" in logs[-1][2]


async def test_barge_in_cancels_speaking():
    gate = asyncio.Event()

    async def slow_brain(*a):
        await gate.wait()
        return "很长的回答。"

    s, sent, _ = make(brain=slow_brain)
    await s.start_turn("讲讲方程")
    await asyncio.sleep(0)
    await s.on_asr_event({"type": "speech_start"})
    assert any(e["type"] == "interrupted" for e in sent)
    assert s.reply_task.cancelled() or s.reply_task.done()
    assert not any(e["type"] == "reply_done" for e in sent)


async def test_session_limit_and_daily_cap():
    clock = Clock()
    s, sent, logs = make(session_limit=600, remaining=3000, clock=clock)
    clock.t += 601
    await s.start_turn("再来一题")
    await _settle(s)
    assert any(e["type"] == "limit" and e["reason"] == "session_limit" for e in sent) and s.closed
    clock2 = Clock()
    s2, sent2, _ = make(session_limit=1200, remaining=100, clock=clock2)
    clock2.t += 101
    await s2.start_turn("再来一题")
    await _settle(s2)
    assert any(e["type"] == "limit" and e["reason"] == "daily_cap" for e in sent2)


async def test_break_suggestion_in_companion_mode():
    clock = Clock()
    s, sent, _ = make(clock=clock)
    clock.t += svc.BREAK_EVERY_SECONDS + 1
    await s.start_turn("下一题")
    await _settle(s)
    assert any(e["type"] == "break_suggestion" for e in sent)


async def test_rate_limited():
    s, sent, _ = make(rate=False)
    await s.start_turn("1加1")
    await _settle(s)
    assert any(e.get("code") == "rate_limited" for e in sent)


async def test_system_kickoff_not_logged_as_student():
    s, sent, logs = make()
    await s.start_turn(svc.PRACTICE_KICKOFF, system=True)
    await _settle(s)
    assert all(role != "student" for role, *_ in logs)
    assert any(e["type"] == "audio" for e in sent)


def test_valid_name():
    assert svc.valid_name("小星") and svc.valid_name("Mimi")
    assert not svc.valid_name("老婆") and not svc.valid_name("x" * 9) and not svc.valid_name("<b>")
