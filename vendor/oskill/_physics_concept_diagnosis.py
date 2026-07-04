"""oskill._physics_concept_diagnosis — 物理概念优先诊断（FCI式）

组合两个 oprim：
  1. oprim.misconception.diagnose_misconception（确定性，按 KU 名关键词挑候选误解）
  2. oprim._physics_concept_diagnostic.generate_concept_diagnostic（LLM，生成诊断题）

无候选误解时返回 None——不为没有已知误解的 KU 硬造诊断题（宁可跳过这一步，
直接进入受力分析计算迁移）。stateless，不持久化（会话落库在 services 层）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ConceptDiagnosisResult:
    """一次物理概念诊断的完整结果（候选误解 + 诊断题）。"""

    misconception_id: str
    remediation: str
    scenario: str
    option_a: str
    option_b: str
    misconception_option: str  # "A" | "B"


async def physics_concept_diagnosis(
    *,
    ku_name: str,
    ku_id: Optional[str],
    caller: Any,
    model: str = "claude-sonnet-4-6",
) -> Optional[ConceptDiagnosisResult]:
    """给定物理 KU，若命中已知误解则生成 FCI 式诊断题，否则返回 None。"""
    from oprim._physics_concept_diagnostic import generate_concept_diagnostic
    from oprim.misconception import diagnose_misconception

    candidate = diagnose_misconception("physics", ku_name, ku_id=ku_id)
    if candidate is None:
        return None

    diag = await generate_concept_diagnostic(
        misconception_label=candidate["label"],
        remediation=candidate["remediation"],
        ku_name=ku_name,
        caller=caller,
        model=model,
    )

    return ConceptDiagnosisResult(
        misconception_id=candidate["id"],
        remediation=candidate["remediation"],
        scenario=diag.scenario,
        option_a=diag.option_a,
        option_b=diag.option_b,
        misconception_option=diag.misconception_option,
    )


__all__ = ["ConceptDiagnosisResult", "physics_concept_diagnosis"]
