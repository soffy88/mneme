"""User-safe error response contract."""

from __future__ import annotations

from typing import Any


def user_safe_error_payload(*, trace_id: str | None = None, code: str = "internal_error", message: str = "服务暂时不可用，请稍后重试。") -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "trace_id": trace_id}}


__all__ = ["user_safe_error_payload"]
