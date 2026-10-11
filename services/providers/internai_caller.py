"""services/providers/internai_caller.py — 上海人工智能实验室 Discovery API（OpenAI 兼容）

## 为什么加它

2026-10-04 实测：Veya 网关侧 **28 个上游只剩 2 个可用**（opencode-go 403/429、
gmi-serving **402 余额耗尽**、nvidia-nim 超时），批量生成基本停摆。而本项目此前的
冗余是「**同一端点换模型名**」—— 端点整个挂掉时，名单里每个模型都会一起失败
（这正是 461 词补齐只完成 8 条的原因）。

所以接一个**独立端点**才有意义：它挂不影响 Veya，Veya 挂不影响它。

## 与 VeyaTextCaller 的关系

**继承**，不复制。它已经具备两样关键东西：

1. 逗号分隔名单的**按序回退**；
2. 回退必须**检查返回内容** —— 网关的故障是 HTTP 200 + 正文错误串，
   只判状态码的话每个模型都「成功」、回退永不触发。

这里只覆写端点、鉴权头、默认模型。

## ⚠️ 它是推理模型，`max_tokens` 要给思考留余量

实测「say PONG」：`completion_tokens=177`，其中 **173 是 `reasoning_tokens`**，
真正可见的 `content` 只有 4 个 token；`max_tokens=12` 时思考就把预算吃光、
`content` 为空且 `finish_reason="length"`。

所以：

- 调用方给的 `max_tokens` 必须**覆盖思考 + 回答**（记忆节点契约用 8192，够用）；
- **答案在 `content`，思考在 `reasoning_content`** —— 本 caller 只取 `content`，
  与 OpenAI 兼容语义一致，不要去读 reasoning_content。
"""

from __future__ import annotations

import os

from services.providers.veya_caller import VeyaTextCaller

DEFAULT_BASE_URL = "https://discovery-api.intern-ai.org.cn/v1"
DEFAULT_MODEL = "Agents-A1"


class InternAiTextCaller(VeyaTextCaller):
    """Discovery API 文本模型。端点/鉴权与 Veya 不同，回退逻辑完全复用。"""

    def _auth_headers(self) -> dict[str, str]:
        key = (
            os.environ.get("INTERN_AI_API_KEY")
            or os.environ.get("INTERN_AI_KEY")
            or ""
        ).strip()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def __init__(self, model: str | None = None) -> None:
        self.base_url = (
            os.environ.get("INTERN_AI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        raw = model or os.environ.get("INTERN_AI_MODEL", DEFAULT_MODEL)
        self.models: list[str] = [m.strip() for m in str(raw).split(",") if m.strip()]
        if not self.models:
            self.models = [DEFAULT_MODEL]
        self.model = self.models[0]
        self.last_good_model: str | None = None


class FallbackTextCaller:
    """跨**端点**的文本回退链。

    与 `VeyaTextCaller` 内部的「同端点换模型」是两层独立的冗余：

        FallbackTextCaller([veya, internai])
          └─ VeyaTextCaller([veya 名单…])      ← 端点 A 内换模型
          └─ InternAiTextCaller([Agents-A1…])  ← 端点 A 全挂 → 换端点 B

    单个端点整体不可用时，只有这一层能救 —— 2026-10-04 的故障正是这种形态
    （不是某个模型坏，是整条上游链坏）。
    """

    def __init__(self, callers: list) -> None:
        self.callers = [c for c in callers if c is not None]
        if not self.callers:
            raise ValueError("FallbackTextCaller 需要至少一个 caller")
        # 对外暴露首个端点的字段，保持与单端点 caller 的可观测性一致
        self.models: list[str] = []
        for c in self.callers:
            self.models.extend(getattr(c, "models", []) or [])
        self.model = self.models[0] if self.models else "unknown"
        self.last_good_model: str | None = None

    async def __call__(self, **kwargs) -> dict:
        attempts: list[str] = []
        for caller in self.callers:
            try:
                result = await caller(**kwargs)
            except Exception as exc:  # noqa: BLE001 — 换下一个端点
                attempts.append(
                    f"{type(caller).__name__}: {type(exc).__name__}: {exc}"[:180]
                )
                continue
            if not _has_content(result):
                # 端点给了 200 但正文为空：同样换下一个端点（不把空串当答案交出去）
                attempts.append(f"{type(caller).__name__}: empty_content")
                continue
            self.last_good_model = getattr(caller, "last_good_model", None) or getattr(
                caller, "model", None
            )
            self.model = self.last_good_model or self.model
            return result
        raise RuntimeError("all text endpoints failed: " + " | ".join(attempts))

    @property
    def has_reasoning_model(self) -> bool:
        return any(bool(getattr(c, "has_reasoning_model", False)) for c in self.callers)


def _has_content(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    content = result.get("content")
    if isinstance(content, str):
        return bool(content.strip()) or bool(result.get("tool_calls"))
    return content is not None and content != [] and content != {}


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "FallbackTextCaller",
    "InternAiTextCaller",
]