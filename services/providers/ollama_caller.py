"""本地 Ollama LLM caller（OpenAI 兼容 /v1/chat/completions）。

用于把内核 LLM 默认 provider 切到本机 Ollama（如 DeepSeek 余额不足时），
让苏格拉底/变式题等文本生成走本地模型。与内核 LLMCaller 接口一致。
注意：仅替换文本 LLM 的 default；VLM(OCR) 不受影响。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class OllamaCaller:
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = (base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

    async def __call__(
        self,
        *,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        import httpx

        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=payload)
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
