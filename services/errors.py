"""User-safe error response contract."""

from __future__ import annotations

from typing import Any


def user_safe_error_payload(*, trace_id: str | None = None, code: str = "internal_error", message: str = "服务暂时不可用，请稍后重试。") -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "trace_id": trace_id}}


class LlmUnavailableError(RuntimeError):
    """LLM 不可用（配置对了但上游全挂）。

    单独立一个异常而不是让 `LLMOprimError` 直接冒到路由，是因为这两种失败的
    **处置完全不同**：

    - `LLMOprimError` = 某次调用失败，通常可重试；
    - 本异常 = **整条链路没有可用模型**，重试只会连续失败。

    2026-10-04 实测就是后者：28 个已知上游里只剩 `space-bunny-free` 间歇可用
    （gmi-serving 402 余额耗尽、opencode-go 403/429、nvidia-nim 超时）。此时
    返回 500 + 栈里的 oprim 异常，对使用者毫无信息量；返回 503 + 明确缺什么，
    才能让人立刻知道该去充额度还是换 key。
    """

    status_code = 503

    def __init__(self, detail: str, *, candidates: list[str] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.candidates = candidates or []


__all__ = ["LlmUnavailableError", "user_safe_error_payload"]
