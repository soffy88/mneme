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
    """注册默认 LLM/VLM provider；`MNEME_LLM=ollama` 时把文本 LLM default 切到本机 Ollama。

    返回生效的文本 LLM 标签（"ollama" 或 "default"）。VLM/OCR 不受影响。
    """
    register_default_providers()

    if os.environ.get("MNEME_LLM", "").lower() == "ollama":
        from obase.provider_registry import ProviderRegistry

        from services.providers.ollama_caller import OllamaCaller

        ProviderRegistry.get().register_llm("default", OllamaCaller(), replace=True)
        ProviderRegistry.get().register_llm("ollama", OllamaCaller(), replace=True)
        return "ollama"

    return "default"
