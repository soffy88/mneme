"""LLM/VLM provider 装配（单源）。

审计 2026-07-03 P0-4：FastAPI lifespan 会在 MNEME_LLM=ollama 时把文本 LLM 的 default
切到本机 Ollama，但 Celery worker 的 _register_providers 只调 register_default_providers()，
不做这层覆盖 → worker 仍用死 DeepSeek key，拍卷 OCR/KU 抽取/变式生成的异步链跑不通。

把这段逻辑抽成单一函数，API 与 worker 共用，保证两侧行为一致。
"""

from __future__ import annotations

import os

from obase.llm import register_default_providers


def configure_llm_providers() -> str:
    """注册 LLM/VLM provider。`MNEME_LLM` 选后端：

    - `qwen`：阿里云通义千问——文本 qwen-plus + 视觉 qwen-vl（中国备案合规）。
      内核 register_default_providers 只支持 Anthropic/Gemini 视觉，这里补上
      Qwen-VL 作为 default VLM（拍卷 OCR 用）。凭据走 DASHSCOPE_API_KEY。
    - `ollama`：本机 Ollama（仅文本，VLM 不受影响）。
    - 其它/空：走内核默认（按 key 优先级 DeepSeek>Qwen>Anthropic>OpenAI）。

    返回生效的文本 LLM 标签。
    """
    register_default_providers()

    backend = os.environ.get("MNEME_LLM", "").lower()

    if backend == "qwen":
        from obase.provider_registry import ProviderRegistry

        from services.providers.qwenvl_caller import QwenTextCaller, QwenVLCaller

        registry = ProviderRegistry.get()
        # 直接从环境读 DASHSCOPE key 自建 caller，不依赖 register_default_providers
        # （它用 `QWEN_API_KEY or DASHSCOPE_API_KEY`，QWEN_API_KEY 占位符
        # "your_key_here" 是 truthy 会短路盖掉真 key）。文本+视觉都走 OpenAI 兼容
        # 端点（base_url 由 QWEN_BASE_URL 配，支持 MaaS 专属部署），用本地自建的
        # QwenTextCaller/QwenVLCaller，不用内核 QwenCaller（后者硬编码公共 host）。
        key = (
            os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or ""
        )
        if key and key != "your_key_here":
            registry.register_llm("default", QwenTextCaller(key), replace=True)
            registry.register_llm("qwen", QwenTextCaller(key), replace=True)
            registry.register_vlm("default", QwenVLCaller(key), replace=True)
            registry.register_vlm("qwen-vl", QwenVLCaller(key), replace=True)
        return "qwen"

    if backend == "ollama":
        from obase.provider_registry import ProviderRegistry

        from services.providers.ollama_caller import OllamaCaller

        ProviderRegistry.get().register_llm("default", OllamaCaller(), replace=True)
        ProviderRegistry.get().register_llm("ollama", OllamaCaller(), replace=True)
        return "ollama"

    return "default"
