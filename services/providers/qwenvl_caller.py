"""阿里云通义千问视觉（Qwen-VL）VLM caller —— DashScope 多模态接口。

内核 VLM 接口只支持 Anthropic/Gemini（海外），本项目要中国备案合规的视觉，
故自建 Qwen-VL 适配器，接口与内核 VLMCaller 一致
（__call__(*, prompt, image_b64, response_format) -> {content, raw_text, usage}），
供拍卷 OCR（oprim.ocr_paper）使用。DashScope 已在网信办备案。

model: qwen-vl-max / qwen-vl-plus。凭据走 DASHSCOPE_API_KEY 环境变量。
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


class QwenVLCaller:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.environ.get("QWEN_VL_MODEL", "qwen-vl-max")

    async def __call__(
        self, *, prompt: str, image_b64: str, response_format: str = "text"
    ) -> dict[str, Any]:
        import httpx

        # DashScope 多模态：图片可传 data URI(base64) 或 URL；这里用 base64 data URI。
        img = (
            image_b64
            if image_b64.startswith("data:")
            else f"data:image/jpeg;base64,{image_b64}"
        )
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"image": img}, {"text": prompt}],
                    }
                ]
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        # output.choices[0].message.content 是 [{"text": "..."}] 形式
        raw_text = ""
        try:
            parts = data["output"]["choices"][0]["message"]["content"]
            raw_text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        except (KeyError, IndexError, TypeError):
            raw_text = ""

        content: Any = raw_text
        if response_format == "json":
            content = _extract_json(raw_text)

        usage = data.get("usage", {})
        return {
            "content": content,
            "raw_text": raw_text,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        }
