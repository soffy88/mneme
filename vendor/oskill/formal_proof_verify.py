"""oskill.formal_proof_verify — Formal proof verification via Mathlib lookup.

3O layer: oskill (组合 mathlib_lookup + 字典映射判定).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field


class FormalProofResult(BaseModel):
    """Result of a formal proof verification."""

    theorem_name: str
    verdict: Literal["proven", "not_elevated"]
    matched_lemma: str | None = None
    matched_module: str | None = None
    evidence: str | None = Field(None, description="established_proof:mathlib:<lemma>:<module>")
    decision_trail: list[dict[str, Any]] = Field(default_factory=list)


def formal_proof_verify(
    *,
    theorem_name: str,
    name_dict: dict[str, str],
    mathlib_lookup_fn: Callable[..., Any],
) -> FormalProofResult:
    """既有定理形式化确证: 查 Mathlib 是否有该定理形式化条目, 唯一命中则判 proven.

    机制: theorem_name 经 name_dict 映射到 Lean 名 → mathlib_lookup 查 →
    count==1 强命中则 verdict=proven (evidence 记 lemma+module);
    不在字典 / 不命中 / 多命中 → not_elevated (宁漏判不错判)。
    运行时无 LLM (守 "proven 非 LLM 自信", ADR-A28: 既有定理信任已有证明)。

    Args:
        theorem_name: 待确证定理名 (可中文).
        name_dict: {theorem_name: lean_name} 映射字典 (调用方注入, 留 Layer4, 不入主库).
        mathlib_lookup_fn: 注入的 oprim.mathlib_lookup (依赖注入, 不直接 import).

    Returns:
        FormalProofResult: verdict + 匹配证据 + decision_trail.

    Raises:
        ValueError: theorem_name 为空.

    Example:
        >>> from oprim import mathlib_lookup
        >>> r = formal_proof_verify(
        ...     theorem_name="加法交换律",
        ...     name_dict={"加法交换律": "Nat.add_comm"},
        ...     mathlib_lookup_fn=mathlib_lookup,
        ... )
        >>> r.verdict
        'proven'
        >>> r.evidence
        'established_proof:mathlib:Nat.add_comm:Mathlib.Algebra...'
    """
    if not theorem_name:
        raise ValueError("theorem_name cannot be empty")

    trail: list[dict[str, Any]] = []

    # 1. 映射判定
    lean_name = name_dict.get(theorem_name)
    if not lean_name:
        trail.append(
            {"step": "mapping", "status": "failed", "detail": f"No mapping for '{theorem_name}'"}
        )
        return FormalProofResult(
            theorem_name=theorem_name,
            verdict="not_elevated",
            evidence=None,
            decision_trail=trail,
        )

    trail.append({"step": "mapping", "status": "success", "lean_name": lean_name})

    # 2. Mathlib 查询
    try:
        lookup_res = mathlib_lookup_fn(identifier=lean_name)
        trail.append(
            {
                "step": "lookup",
                "status": "success",
                "count": lookup_res.count,
                "hits": [h.dict() for h in lookup_res.hits],
            }
        )
    except Exception as e:
        trail.append({"step": "lookup", "status": "error", "error": str(e)})
        return FormalProofResult(
            theorem_name=theorem_name,
            verdict="not_elevated",
            evidence=None,
            decision_trail=trail,
        )

    # 3. 结果判定
    if lookup_res.count == 1:
        hit = lookup_res.hits[0]
        evidence = f"established_proof:mathlib:{hit.name}:{hit.module}"
        trail.append({"step": "verdict", "status": "proven", "evidence": evidence})
        return FormalProofResult(
            theorem_name=theorem_name,
            verdict="proven",
            matched_lemma=hit.name,
            matched_module=hit.module,
            evidence=evidence,
            decision_trail=trail,
        )

    status = "ambiguous" if lookup_res.count > 1 else "not_found"
    trail.append({"step": "verdict", "status": "not_elevated", "reason": status})
    return FormalProofResult(
        theorem_name=theorem_name,
        verdict="not_elevated",
        evidence=None,
        decision_trail=trail,
    )
