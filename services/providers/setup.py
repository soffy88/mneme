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
from obase.provider_registry import ProviderRegistry
from services.providers.reliability import ReliableProvider, wrap_provider

logger = logging.getLogger(__name__)

_MOCK_TYPE_NAMES = frozenset({"_MockLLM", "_MockVLM"})
_CONFIGURATION_SIGNATURE: tuple[tuple[str, str], ...] | None = None


def _configuration_signature() -> tuple[tuple[str, str], ...]:
    """Track non-secret provider configuration without retaining secret values."""

    names = (
        "MNEME_LLM",
        "QWEN_BASE_URL",
        "QWEN_MODEL",
        "QWEN_VL_MODEL",
        "VEYA_BASE_URL",
        "VEYA_MODEL",
        "VEYA_VL_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
    )
    key_presence = (
        ("DASHSCOPE_API_KEY", "1" if os.environ.get("DASHSCOPE_API_KEY") else "0"),
        ("QWEN_API_KEY", "1" if os.environ.get("QWEN_API_KEY") else "0"),
        ("DEEPSEEK_API_KEY", "1" if os.environ.get("DEEPSEEK_API_KEY") else "0"),
        ("OPENAI_API_KEY", "1" if os.environ.get("OPENAI_API_KEY") else "0"),
        ("ANTHROPIC_API_KEY", "1" if os.environ.get("ANTHROPIC_API_KEY") else "0"),
        ("GEMINI_API_KEY", "1" if os.environ.get("GEMINI_API_KEY") else "0"),
    )
    return tuple((name, os.environ.get(name, "")) for name in names) + key_presence


def _allow_mock() -> bool:
    """测试/CI 可显式允许 mock；默认在 demo/prod 声明 qwen 时不允许。"""
    if os.environ.get("MNEME_ALLOW_MOCK_LLM", "").lower() in ("1", "true", "yes"):
        return True
    # pytest 进程默认允许（避免炸测试）
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False


def provider_status() -> dict[str, Any]:
    """当前 default LLM/VLM **配置**状态（无密钥、无内容、不发任何请求）。

    供 /health 与 pilot 冒烟。

    ⚠️ **这里刻意不做网络探测。** `configure_llm_providers()` 每次装配都会调本函数
    打一行日志，若把可达性探针放进来，等于**每次装配都多付 3 秒网络超时**
    （第一版就踩了这个：`tool_generate_memory_node` 一次生成凭空多 3 秒）。
    可达性是**活探针**，属于 /health/providers 端点的职责，见
    `probe_llm_usable()` / `_probe_endpoint_reachable()`。
    """
    from obase.provider_registry import ProviderRegistry

    reg = ProviderRegistry.get()
    try:
        llm = reg.llm()
        llm_name = type(getattr(llm, "caller", llm)).__name__
    except Exception as e:  # noqa: BLE001 — 状态探测
        llm_name = f"error:{type(e).__name__}"
    try:
        vlm = reg.vlm()
        vlm_name = type(getattr(vlm, "caller", vlm)).__name__
    except Exception as e:  # noqa: BLE001
        vlm_name = f"error:{type(e).__name__}"
    return {
        "mneme_llm": os.environ.get("MNEME_LLM", "") or "default",
        "llm": llm_name,
        "vlm": vlm_name,
        "llm_is_mock": llm_name in _MOCK_TYPE_NAMES,
        "vlm_is_mock": vlm_name in _MOCK_TYPE_NAMES,
        # 未探测：可达性要发请求，不属于配置快照。见 /health/providers。
        "llm_reachable": None,
        "qwen_model": os.environ.get("QWEN_MODEL"),
        "qwen_vl_model": os.environ.get("QWEN_VL_MODEL"),
        "veya_model": os.environ.get("VEYA_MODEL"),
        "veya_vl_model": os.environ.get("VEYA_VL_MODEL"),
    }


async def provider_liveness(*, deep: bool = False, timeout: float = 3.0) -> dict[str, Any]:
    """**活探针**：配置 + 网关可达性（+ 可选真实补全）。

    与 :func:`provider_status` 分开，因为它会发网络请求。`/health/providers` 用它；
    装配路径不要用（会平白多付一次超时）。

    **必须是 async**：本函数由 async 的路由处理器调用。第一版用同步的
    `asyncio.run()` 包探针，结果在生产实测里直接抛
    `RuntimeError: asyncio.run() cannot be called from a running event loop`
    —— 也就是 deep 探针从来没真正跑过。同步的 urllib 探活走
    `asyncio.to_thread`，否则会把事件循环堵住 3 秒。
    """
    import asyncio

    status = provider_status()
    endpoint = await asyncio.to_thread(_probe_endpoint_reachable, timeout)
    status["llm_reachable"] = endpoint["reachable"]
    status["llm_reachable_detail"] = endpoint["detail"]
    status["llm_usable_checked"] = "endpoint_only"
    if status["llm_is_mock"]:
        # 测试/CI 明确允许 mock：mock 就是「可用」，别报成故障。
        status["llm_usable"] = True
        status["llm_usable_detail"] = "mock_allowed"
        return status
    if deep:
        verdict = await probe_llm_usable()
        status["llm_usable"] = bool(verdict["usable"]) and endpoint["reachable"]
        status["llm_usable_detail"] = verdict["detail"]
        status["llm_usable_checked"] = "deep"
    else:
        status["llm_usable"] = endpoint["reachable"]
        status["llm_usable_detail"] = "endpoint_only"
    return status


# 网关会用 **HTTP 200** 把上游故障当正文返回，例如 2026-10-03 实测：
#   {"choices":[{"message":{"content":"gpt-5.6-luna 兜底失败"}}]}
#   {"choices":[{"message":{"content":"opencode-go rejected the request (HTTP 429): ...
#      Go usage limit exceeded"}}]}
# 所以「没抛异常」**不等于**成功 —— 只判异常的探针会把「文本 LLM 调不通」报成健康。
# 第一版探针就栽在这里：`max_tokens=1` + 只看异常 → 退役别名 veya1.2-128K 显示
# reachable=true，而它实际每次都返回上面那串兜底失败。
_GATEWAY_ERROR_MARKERS = (
    "兜底失败",
    "rejected the request",
    "usage limit",
    "no api-key",
    "rate_limit",
    "insufficient_quota",
    "service unavailable",
)


def _looks_like_gateway_error(text: str | None) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _GATEWAY_ERROR_MARKERS)


def _probe_endpoint_reachable(timeout: float = 3.0) -> dict[str, Any]:
    """只探网关端点答不答话（GET /models），不发 token、不看内容。"""
    base = os.environ.get("VEYA_BASE_URL") or os.environ.get("QWEN_BASE_URL")
    if not base:
        return {"reachable": False, "detail": "no_base_url"}
    url = base.rstrip("/") + "/models"
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            code = getattr(resp, "status", 200)
        return {"reachable": code == 200, "detail": f"http_{code}"}
    except Exception as exc:  # noqa: BLE001 — 探针失败就是结论
        return {"reachable": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}


async def probe_llm_usable(timeout: float = 30.0) -> dict[str, Any]:
    """真发一次最小补全并**检查内容**。慢（3~30s），故只在显式请求时跑。

    这是唯一能识破「HTTP 200 + 正文是错误串」的检查。

    **async**：由 async 路由处理器 await（见 :func:`provider_liveness` 的说明）。
    """
    import asyncio

    try:
        from oprim.llm import llm_complete
        from obase.provider_registry import ProviderRegistry

        caller = ProviderRegistry.get().llm("default")

        async def _probe() -> str:
            resp = await llm_complete(
                [{"role": "user", "content": "Reply with exactly: PONG"}],
                caller=caller,
                model=os.environ.get("VEYA_MODEL") or "veya1.2",
                max_tokens=8,
            )
            return resp.text or ""

        text = (await asyncio.wait_for(_probe(), timeout=timeout)).strip()
    except asyncio.TimeoutError:
        # 单独说清楚：空消息的 "TimeoutError: " 对运维毫无信息。
        # 实测有的模型能回内容但要 68~90s（veya-deepseek-v4-flash-nv），
        # 那不叫「可用」——学习产品里的生成必须能同步等得起。
        return {
            "usable": False,
            "detail": f"timeout_after_{timeout:g}s_slow_or_unreachable",
            "text": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"usable": False, "detail": f"{type(exc).__name__}: {exc}"[:200], "text": None}
    if _looks_like_gateway_error(text):
        return {
            "usable": False,
            "detail": "gateway_returned_error_payload",
            "text": text[:120],
        }
    if not text:
        return {"usable": False, "detail": "empty_completion", "text": None}
    return {"usable": True, "detail": "ok", "text": text[:40]}


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
    global _CONFIGURATION_SIGNATURE

    signature = _configuration_signature()
    registry = ProviderRegistry.get()
    # ProviderRegistry is process-global. Clear only the LLM/VLM stores before
    # rebuilding, leaving unrelated ASR/TTS/pronunciation registrations intact.
    registry._llms.clear()
    registry._vlms.clear()
    register_default_providers()

    backend = os.environ.get("MNEME_LLM", "").lower()

    if backend == "veya":
        from services.providers.veya_caller import VeyaTextCaller, VeyaVLCaller

        registry = ProviderRegistry.get()
        registry.register_llm("default", VeyaTextCaller(), replace=True)
        registry.register_llm("veya", VeyaTextCaller(), replace=True)
        registry.register_vlm("default", VeyaVLCaller(), replace=True)
        registry.register_vlm("veya-vl", VeyaVLCaller(), replace=True)
        _install_reliability_wrappers(backend)
        _CONFIGURATION_SIGNATURE = signature
        return "veya"

    if backend == "qwen":
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
            _install_reliability_wrappers(backend)
            _CONFIGURATION_SIGNATURE = signature
            return "qwen"

        msg = (
            "MNEME_LLM=qwen 但 DASHSCOPE_API_KEY/QWEN_API_KEY 缺失或占位符——"
            "若继续将静默使用 _MockLLM/_MockVLM，拍卷会出假批改。"
        )
        if not _allow_mock():
            logger.error(msg + " 拒绝启动装配（设 MNEME_ALLOW_MOCK_LLM=1 可强制允许）。")
            raise RuntimeError(msg)
        logger.warning(msg + " 当前允许 mock（测试或 MNEME_ALLOW_MOCK_LLM=1）。")
        _install_reliability_wrappers(backend)
        _CONFIGURATION_SIGNATURE = signature
        return "qwen-missing-key-mock"

    if backend == "ollama":
        from services.providers.ollama_caller import OllamaCaller

        ProviderRegistry.get().register_llm("default", OllamaCaller(), replace=True)
        ProviderRegistry.get().register_llm("ollama", OllamaCaller(), replace=True)
        _install_reliability_wrappers(backend)
        _CONFIGURATION_SIGNATURE = signature
        return "ollama"

    status = provider_status()
    if (
        os.environ.get("MNEME_ENV", "").strip().lower() == "production"
        and status["llm_is_mock"]
    ):
        # A production process must never turn a missing provider into a
        # plausible-looking model response.  The core learning path can still
        # run without an LLM when the caller is optional, but the deployment
        # itself must fail closed before serving LLM-dependent traffic.
        raise RuntimeError("production requires a live LLM provider; mock is forbidden")
    if status["llm_is_mock"] or status["vlm_is_mock"]:
        logger.warning(
            "LLM/VLM default 为 mock（llm=%s vlm=%s）。生产教学请配置可用的 MNEME_LLM provider。",
            status["llm"],
            status["vlm"],
        )
    _install_reliability_wrappers(backend)
    _CONFIGURATION_SIGNATURE = signature
    return "default"


def _provider_label(caller: Any, registered_name: str, backend: str) -> str:
    """Map registry entries to bounded provider labels, never request data."""

    if registered_name not in {"default", "qwen-vl", "veya-vl"}:
        return registered_name
    class_name = type(caller).__name__.lower()
    for label in ("deepseek", "qwen", "veya", "ollama", "anthropic", "openai", "gemini"):
        if label in class_name:
            return label
    return backend or "default"


def _install_reliability_wrappers(backend: str) -> None:
    """Wrap every registry LLM/VLM entry exactly once after provider setup."""

    registry = ProviderRegistry.get()
    wrappers: dict[tuple[str, str, str], ReliableProvider] = {}
    for name, llm_caller in list(registry._llms.items()):  # central registry has no iteration API
        if not isinstance(llm_caller, ReliableProvider):
            provider = _provider_label(llm_caller, name, backend)
            model = str(getattr(llm_caller, "model", "unknown"))
            key = (provider, model, "llm")
            if key not in wrappers:
                wrappers[key] = wrap_provider(
                    llm_caller,
                    provider=provider,
                    model=model,
                    kind="llm",
                    # LLM/VLM completion is the only retryable operation in
                    # this contract: it has no Mneme-side write.  Evidence,
                    # mastery and FSRS writes happen only after the caller
                    # returns once to the surrounding transaction.
                    retryable=True,
                )
            registry._llms[name] = wrappers[key]
    for name, vlm_caller in list(registry._vlms.items()):
        if not isinstance(vlm_caller, ReliableProvider):
            provider = _provider_label(vlm_caller, name, backend)
            model = str(getattr(vlm_caller, "model", "unknown"))
            key = (provider, model, "vlm")
            if key not in wrappers:
                wrappers[key] = wrap_provider(
                    vlm_caller,
                    provider=provider,
                    model=model,
                    kind="vlm",
                    retryable=True,
                )
            registry._vlms[name] = wrappers[key]


def get_text_caller() -> Any:
    """Return the centrally configured, reliability-wrapped text provider."""

    global _CONFIGURATION_SIGNATURE
    instance_missing = ProviderRegistry._instance is None
    registry = ProviderRegistry.get()
    if instance_missing or not ProviderRegistry.has("llm", "default"):
        configure_llm_providers()
    elif _CONFIGURATION_SIGNATURE is not None and _CONFIGURATION_SIGNATURE != _configuration_signature():
        configure_llm_providers()
    else:
        # Tests and callers may inject a registry entry directly.  Preserve it,
        # but still enforce the same reliability contract at this boundary.
        _install_reliability_wrappers(os.environ.get("MNEME_LLM", "").lower())
    return registry.llm()


def get_vision_caller() -> Any:
    """Return the centrally configured, reliability-wrapped vision provider."""

    global _CONFIGURATION_SIGNATURE
    instance_missing = ProviderRegistry._instance is None
    registry = ProviderRegistry.get()
    if instance_missing or not ProviderRegistry.has("vlm", "default"):
        configure_llm_providers()
    elif _CONFIGURATION_SIGNATURE is not None and _CONFIGURATION_SIGNATURE != _configuration_signature():
        configure_llm_providers()
    else:
        _install_reliability_wrappers(os.environ.get("MNEME_LLM", "").lower())
    return registry.vlm()


def get_optional_text_caller() -> Any | None:
    """Return a reliable live caller for optional features, else ``None``.

    A mock is deliberately treated as unavailable here.  Optional generation
    may degrade to its deterministic/template path, while a mock must never
    be mistaken for provider-backed evidence.
    """

    try:
        caller = get_text_caller()
    except Exception:  # noqa: BLE001 - optional dependency boundary
        return None
    if type(getattr(caller, "caller", caller)).__name__ in _MOCK_TYPE_NAMES:
        return None
    return caller


def get_agent_loop_caller() -> ReliableProvider:
    """Return the tool-calling adapter under the same reliability contract.

    The agent loop has a richer protocol than the registry's simple completion
    callers, so it gets its own adapter, but never its own retry/timeout policy.
    The adapter only reads server-side environment configuration; no key is
    returned in status, logs, metrics, or the frontend.
    """

    backend = os.environ.get("MNEME_LLM", "").strip().lower()
    caller: Any
    if backend == "veya":
        from mneme_agent.qwen_llm import VeyaLoopCaller

        caller = VeyaLoopCaller()
    elif backend == "qwen":
        from mneme_agent.qwen_llm import QwenLoopCaller

        key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
        if not key or key == "your_key_here":
            raise RuntimeError("chat provider key is not configured")
        caller = QwenLoopCaller(
            api_key=key,
            model=os.environ.get("QWEN_MODEL"),
        )
    elif backend == "ollama":
        from mneme_agent.qwen_llm import OpenAICompatibleLoopCaller

        base_url = (
            os.environ.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434"
        ).rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        caller = OpenAICompatibleLoopCaller(
            api_key=os.environ.get("OLLAMA_API_KEY") or None,
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            base_url=base_url,
        )
    else:
        raise RuntimeError(
            f"chat provider backend is unsupported: {backend or 'default'}"
        )
    return wrap_provider(
        caller,
        provider=backend,
        model=str(getattr(caller, "model", "unknown")),
        kind="llm",
        retryable=True,
    )
