"""语音转数学符号文本 (oprim_speech_to_math)

职责：将中学生口述的数学问题/解题步骤转换为含 LaTeX 的文本。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional

@dataclass(frozen=True)
class SpeechToMathInput:
    """语音输入。"""
    audio_b64: str = ""
    audio_url: str | None = None
    language: str = "zh-CN"
    # 可选：上下文提示，如“正在做二次函数题目”
    context_hint: Optional[str] = None

@dataclass(frozen=True)
class SpeechToMathResult:
    """语音识别结果。"""
    text: str = ""
    latex_text: str = ""
    confidence: float = 0.0
    # 低置信度标记需二次确认的 token 区间
    uncertain_tokens: List[str] = field(default_factory=list)
    success: bool = True
    error: str = ""

_STT_SYSTEM = (
    "你是一个数学语音识别专家。将语音转写的文本转换为规范的数学表达（含 LaTeX）。\n"
    "对于口语化的描述（如“x 平方加二 x”），转换为 “$x^2 + 2x$”。\n"
    "输出 JSON 格式：\n"
    "{\n"
    "  \"text\": \"原始识别文本\",\n"
    "  \"latex_text\": \"含 LaTeX 的数学规范文本\",\n"
    "  \"confidence\": 0.95,\n"
    "  \"uncertain_tokens\": [\"可能不准确的词\"]\n"
    "}\n"
    "如果识别完全失败，success 设为 false。"
)

async def speech_to_math(
    inp: SpeechToMathInput,
    *,
    caller: Any,
    model: str = "gpt-4o-audio-preview" # 假设使用支持音频的模型
) -> SpeechToMathResult:
    """处理语音转数学。"""
    import json
    from oprim.llm._llm_complete import llm_complete

    # 构造音频消息（具体格式取决于 llm_complete 的实现，这里假设支持直接传递音频块）
    content = []
    if inp.audio_url:
        content.append({"type": "audio", "audio_url": inp.audio_url})
    elif inp.audio_b64:
        content.append({"type": "audio", "audio_b64": inp.audio_b64})
    else:
        return SpeechToMathResult(success=False, error="No audio provided")

    content.append({"type": "text", "text": f"请将这段关于数学的语音转写为文本，并提取 LaTeX 公式。语言: {inp.language}"})
    if inp.context_hint:
        content.append({"type": "text", "text": f"上下文提示: {inp.context_hint}"})

    messages = [{"role": "user", "content": content}]

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=_STT_SYSTEM,
            model=model
        )
        
        raw = response.text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        
        data = json.loads(raw)
        return SpeechToMathResult(
            text=data.get("text", ""),
            latex_text=data.get("latex_text", ""),
            confidence=data.get("confidence", 0.0),
            uncertain_tokens=data.get("uncertain_tokens", []),
            success=True
        )
    except Exception as e:
        return SpeechToMathResult(success=False, error=str(e))

__version__ = "0.1.0"
