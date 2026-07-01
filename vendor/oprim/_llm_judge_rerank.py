from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel

from oprim._exceptions import OprimError


class LLMCaller(Protocol):
    """LLM 调用的 Protocol."""

    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
    ) -> dict[str, Any]: ...


class RerankResult(BaseModel):
    """Rerank 的结果项."""

    original_index: int
    score: float


_RERANK_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$", flags=re.MULTILINE)


def llm_judge_rerank(
    *,
    query: str,
    documents: list[str],
    llm: LLMCaller,
    top_k: int | None = None,
) -> list[RerankResult]:
    """使用 LLM 作为 Judge 给文档重新打分排序.

    Args:
        query: 用户查询
        documents: 待排序文档文本列表
        llm: LLM 调用函数
        top_k: 截断数量

    Returns:
        重新排序后的 RerankResult 列表

    Raises:
        OprimError: 如果请求为空或执行失败

    Example:
        ```python
        def dummy_llm(**kwargs):
            return {"content": "0: 9\\n1: 1"}
        
        docs = ["highly relevant", "irrelevant"]
        res = llm_judge_rerank(query="test", documents=docs, llm=dummy_llm)
        assert res[0].original_index == 0
        assert res[0].score == 1.0
        ```
    """
    if not query.strip():
        raise OprimError("Query cannot be empty")

    if not documents:
        return []

    docs_text = "\\n\\n".join([f"[{i}] {doc}" for i, doc in enumerate(documents)])
    prompt = f"""Please rate the relevance of the following documents to the query.
Query: {query}

Documents:
{docs_text}

Rate each document from 1 to 10. Output format MUST be exactly:
index: score
For example:
0: 9
1: 5
"""

    messages = [{"role": "user", "content": prompt}]
    
    try:
        response = llm(messages=messages)
        content = response.get("content", "")
    except Exception as e:
        # Fallback due to LLM failure: return 0.0 scores
        return [RerankResult(original_index=i, score=0.0) for i in range(len(documents))][:top_k]

    results_map = {}
    for match in _RERANK_RE.finditer(content):
        idx = int(match.group(1))
        score_raw = int(match.group(2))
        
        if 0 <= idx < len(documents):
            # Normalize to [0, 1]
            score_norm = max(0.0, min(1.0, (score_raw - 1) / 9.0))
            results_map[idx] = score_norm

    # Build final list, fallback 0.0 for missing
    results = []
    for i in range(len(documents)):
        score = results_map.get(i, 0.0)
        results.append(RerankResult(original_index=i, score=score))

    # Sort descending
    results.sort(key=lambda x: x.score, reverse=True)

    if top_k is not None:
        results = results[:top_k]

    return results
