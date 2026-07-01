"""Auto-split from hicode whl."""

from __future__ import annotations
from .._exceptions import OprimError, LLMOprimError, BudgetExceededError, PromptOprimError, SearchOprimError, HttpOprimError, SnapshotOprimError
from ._types import LLMResponse, StreamDelta, EmbedResult, ConversationSnapshot, ThinkingResult, SearchResult, HttpResponse
import json
from collections.abc import AsyncIterator
from typing import Any
from .._protocols import EmbedCaller, StreamingLLMCaller

async def embed_text(
    text: str,
    *,
    caller: EmbedCaller,
    model: str = "text-embedding-3-small",
) -> EmbedResult:
    """单次文本嵌入调用，返回向量。

    async 本性：外部 API IO 等待。

    Args:
        text: 待嵌入的文本字符串。
        caller: EmbedCaller Protocol 实例（由调用方注入）。
        model: 嵌入模型名，默认 text-embedding-3-small。

    Returns:
        EmbedResult(vector, model, token_count)。

    Raises:
        LLMOprimError: 文本为空或嵌入调用失败。

    Example:
        >>> result = await embed_text("hello world", caller=embed_caller)
        >>> len(result.vector)
        1536
    """
    if not text or not text.strip():
        raise LLMOprimError("embed_text: text must not be empty")

    try:
        vector = await caller(text=text, model=model)
    except (LLMOprimError,):
        raise  # pragma: no cover
    except Exception as e:
        raise LLMOprimError("embed_text call failed", cause=e)

    if not isinstance(vector, list) or not vector:
        raise LLMOprimError(
            f"embed_text: caller returned invalid vector type: {type(vector).__name__}"
        )

    token_count = max(1, len(text.split()))  # 粗估
    return EmbedResult(vector=vector, model=model, token_count=token_count)
