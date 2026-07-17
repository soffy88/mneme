"""阿里云通义千问 caller（文本 + 视觉），走 OpenAI 兼容端点。

用户用的是阿里云 MaaS 专属部署（自定义 host，非公共 dashscope.aliyuncs.com），
但提供 OpenAI 兼容模式（/compatible-mode/v1/chat/completions），文本和视觉都能
用同一套 chat/completions 调。base_url/api_key/model 全走环境变量，不硬编码。

- QwenTextCaller：文本 LLM，接口同内核 LLMCaller。
- QwenVLCaller：视觉 VLM（拍卷 OCR），接口同内核 VLMCaller
  （__call__(*, prompt, image_b64, response_format) -> {content, raw_text, usage}）。
  内核只支持 Anthropic/Gemini 视觉，中国备案合规视觉自建。

实测（2026-07-10）：文本 qwen3.7-plus、视觉 qwen-vl-max/qwen-vl-ocr 均端到端通。
"""

from __future__ import annotations

import json
import os
from typing import Any


def _extract_json(text: str) -> Any:
    """从模型输出里尽量抠出 JSON（兼容 ```json 代码块 / 裸 JSON）。抠不出返回原文。"""
    t = text.strip()
    if "```json" in t:
        t = t.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in t:
        t = t.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(t)
    except Exception:
        return text


def _base_url() -> str:
    # 默认公共 DashScope 兼容端点；MaaS 专属部署走 QWEN_BASE_URL 覆盖。
    return (
        os.environ.get("QWEN_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")


class QwenTextCaller:
    """通义千问文本（OpenAI 兼容 chat/completions）。"""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get("QWEN_MODEL", "qwen-plus")
        self.base_url = _base_url()

    async def __call__(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int = 1000,
        tools: list[dict[str, Any]] | None = None,
        response_format: str | None = None,
        system: str | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        import httpx

        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        # qwen3.x 思考模型默认开思维链（慢，判分类任务无需）：显式关掉可从 ~50s 降到 ~2s。
        # DashScope OpenAI 兼容端点接受顶层 enable_thinking（非 extra_body）。
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }


class QwenVLCaller:
    """通义千问视觉（OpenAI 兼容 chat/completions + image_url）。"""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get("QWEN_VL_MODEL", "qwen-vl-max")
        self.base_url = _base_url()

    async def __call__(
        self, *, prompt: str, image_b64: str, response_format: str = "text"
    ) -> dict[str, Any]:
        import httpx

        url = (
            image_b64
            if image_b64.startswith("data:")
            else f"data:image/jpeg;base64,{image_b64}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            "max_tokens": 2000,
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_text = data["choices"][0]["message"]["content"] or ""
        content: Any = (
            _extract_json(raw_text) if response_format == "json" else raw_text
        )
        usage = data.get("usage", {})
        return {
            "content": content,
            "raw_text": raw_text,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }
