"""LLM/VLM provider 装配（单源）。

审计 2026-07-03 P0-4：FastAPI lifespan 会在 MNEME_LLM=ollama 时把文本 LLM 的 default
切到本机 Ollama，但 Celery worker 的 _register_providers 只调 register_default_providers()，
不做这层覆盖 → worker 仍用死 DeepSeek key，拍卷 OCR/KU 抽取/变式生成的异步链跑不通。

把这段逻辑抽成单一函数，API 与 worker 共用，保证两侧行为一致。

Y.4 复检（2026-07-28）：禁止在声明使用云模型时静默落到 _MockLLM/_MockVLM
（假批改比功能缺失更糟）。可用 `MNEME_ALLOW_MOCK_LLM=1` 显式允许（测试/CI）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from obase.llm import register_default_providers

logger = logging.getLogger(__name__)

_MOCK_TYPE_NAMES = frozenset({"_MockLLM", "_MockVLM"})


def _allow_mock() -> bool:
    """测试/CI 可显式允许 mock；默认在 demo/prod 声明 qwen 时不允许。"""
    if os.environ.get("MNEME_ALLOW_MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return True
    # pytest 进程默认允许（避免炸测试）
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False


def provider_status() -> dict[str, Any]:
    """当前 default LLM/VLM 类型（无密钥、无内容）。供 /health 与 pilot 冒烟。"""
    from obase.provider_registry import ProviderRegistry

    reg = ProviderRegistry.get()
    try:
        llm = reg.llm()
        llm_name = type(llm).__name__
    except Exception as e:  # noqa: BLE001 — 状态探测
        llm_name = f"error:{type(e).__name__}"
    try:
        vlm = reg.vlm()
        vlm_name = type(vlm).__name__
    except Exception as e:  # noqa: BLE001
        vlm_name = f"error:{type(e).__name__}"
    return {
        "mneme_llm": os.environ.get("MNEME_LLM", "") or "default",
        "llm": llm_name,
        "vlm": vlm_name,
        "llm_is_mock": llm_name in _MOCK_TYPE_NAMES,
        "vlm_is_mock": vlm_name in _MOCK_TYPE_NAMES,
        "qwen_model": os.environ.get("QWEN_MODEL"),
        "qwen_vl_model": os.environ.get("QWEN_VL_MODEL"),
        "veya_model": os.environ.get("VEYA_MODEL"),
        "veya_vl_model": os.environ.get("VEYA_VL_MODEL"),
    }


def configure_llm_providers() -> str:
    """注册 LLM/VLM provider。`MNEME_LLM` 选后端：

    - `veya`：本机 Veya gateway——文本 veya1.2-128K + 视觉 veya1.2-vl。
    - `qwen`：阿里云通义千问——文本 qwen-plus + 视觉 qwen-vl（中国备案合规）。
      内核 register_default_providers 只支持 Anthropic/Gemini 视觉，这里补上
      Qwen-VL 作为 default VLM（拍卷 OCR 用）。凭据走 DASHSCOPE_API_KEY。
    - `ollama`：本机 Ollama（仅文本，VLM 不受影响）。
    - 其它/空：走内核默认（按 key 优先级 DeepSeek>Qwen>Anthropic>OpenAI）。

    返回生效的文本 LLM 标签。
    """
    register_default_providers()

    backend = os.environ.get("MNEME_LLM", "").lower()

    if backend == "veya":
        from obase.provider_registry import ProviderRegistry

        from services.providers.veya_caller import VeyaTextCaller, VeyaVLCaller

        registry = ProviderRegistry.get()
        registry.register_llm("default", VeyaTextCaller(), replace=True)
        registry.register_llm("veya", VeyaTextCaller(), replace=True)
        registry.register_vlm("default", VeyaVLCaller(), replace=True)
        registry.register_vlm("veya-vl", VeyaVLCaller(), replace=True)
        return "veya"

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
            status = provider_status()
            logger.info(
                "LLM providers: qwen live llm=%s vlm=%s",
                status["llm"],
                status["vlm"],
            )
            return "qwen"

        msg = (
            "MNEME_LLM=qwen 但 DASHSCOPE_API_KEY/QWEN_API_KEY 缺失或占位符——"
            "若继续将静默使用 _MockLLM/_MockVLM，拍卷会出假批改。"
        )
        if not _allow_mock():
            logger.error(msg + " 拒绝启动装配（设 MNEME_ALLOW_MOCK_LLM=1 可强制允许）。")
            raise RuntimeError(msg)
        logger.warning(msg + " 当前允许 mock（测试或 MNEME_ALLOW_MOCK_LLM=1）。")
        return "qwen-missing-key-mock"

    if backend == "ollama":
        from obase.provider_registry import ProviderRegistry

        from services.providers.ollama_caller import OllamaCaller

        ProviderRegistry.get().register_llm("default", OllamaCaller(), replace=True)
        ProviderRegistry.get().register_llm("ollama", OllamaCaller(), replace=True)
        return "ollama"

    status = provider_status()
    if status["llm_is_mock"] or status["vlm_is_mock"]:
        logger.warning(
            "LLM/VLM default 为 mock（llm=%s vlm=%s）。生产教学请配置可用的 MNEME_LLM provider。",
            status["llm"],
            status["vlm"],
        )
    return "default"
