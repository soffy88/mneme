"""相似历史场景注入 — 向量检索 + LLM 上下文拼装 (oskill B10)."""

from __future__ import annotations

from typing import Any

import numpy as np
import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel

from oskill._exceptions import OskillError
from oskill._llm_caller import LLMCaller


class SimilarContextResult(BaseModel):
    """similar_context_injector 结果.

    Attributes:
        top_k_matches:   相似历史场景列表 (label, similarity_score).
        prompt_with_context: 注入历史场景后的完整 LLM prompt.
        llm_response:   LLM 返回的原始结果字典.
    """

    top_k_matches: list[dict[str, Any]]
    prompt_with_context: str
    llm_response: dict[str, Any]


def similar_context_injector(
    *,
    anchor_vec: list[float],
    history_vecs: list[tuple[str, list[float]]],
    context_template: str,
    llm_caller: LLMCaller,
    top_k: int = 5,
) -> SimilarContextResult:
    """Retrieve top-k similar historical scenarios and inject them into an LLM prompt.

    Internal oprim composition:
    - oprim.zscore_normalize       (normalises anchor vector across dimensions)
    - oprim.cosine_similarity_batch (finds top-k nearest historical vectors)

    The LLM is called via the injected :class:`~oskill._llm_caller.LLMCaller` Protocol;
    no LLM SDK is imported directly.

    Args:
        anchor_vec:       Current state vector (list of floats).
        history_vecs:     List of ``(label, vec)`` historical scenarios.
                          All vectors must have the same dimensionality as ``anchor_vec``.
        context_template: Jinja-style string with ``{context}`` placeholder.
        llm_caller:       LLM callable satisfying :class:`LLMCaller` Protocol.
        top_k:            Number of similar scenarios to retrieve.

    Returns:
        :class:`SimilarContextResult`.

    Raises:
        OskillError: If ``anchor_vec`` and history vectors have mismatched dimensions,
                     or ``history_vecs`` is empty.

    Example:
        >>> def fake_llm(*, messages, **kw): return {"content": "ok", "stop_reason": "end"}
        >>> r = similar_context_injector(
        ...     anchor_vec=[1.0, 0.0],
        ...     history_vecs=[("2020-01", [1.0, 0.0]), ("2019-01", [0.0, 1.0])],
        ...     context_template="历史相似: {context}",
        ...     llm_caller=fake_llm,
        ... )
        >>> "2020-01" in r.prompt_with_context
        True
    """
    if not history_vecs:
        raise OskillError("history_vecs must not be empty")
    n_dims = len(anchor_vec)
    if any(len(v) != n_dims for _, v in history_vecs):
        raise OskillError("All history vectors must match anchor_vec dimensionality")

    anchor_sr = pd.Series(anchor_vec, dtype=float)
    norm_anchor = oprim.zscore_normalize(anchor_sr, window=None).to_numpy()

    labels = [label for label, _ in history_vecs]
    hist_matrix = np.array([v for _, v in history_vecs], dtype=np.float64)

    raw = oprim.cosine_similarity_batch(
        query=norm_anchor,
        database=hist_matrix,
        pre_normalize=True,
        top_k=min(top_k, len(history_vecs)),
    )
    if isinstance(raw, tuple):
        sim_scores, top_indices = raw
    else:
        sim_scores = raw
        top_indices = np.argsort(sim_scores)[::-1][:top_k]

    matches = [
        {"label": labels[int(idx)], "similarity": float(sim_scores[i])}
        for i, idx in enumerate(top_indices)
    ]

    context_str = "\n".join(f"- {m['label']} (similarity={m['similarity']:.3f})" for m in matches)
    prompt_text = context_template.replace("{context}", context_str)

    llm_response = llm_caller(
        messages=[{"role": "user", "content": prompt_text}],
        max_tokens=1024,
    )

    return SimilarContextResult(
        top_k_matches=matches,
        prompt_with_context=prompt_text,
        llm_response=llm_response,
    )
