"""P-AII-1: failure_lesson_extract — pure-rule lesson generation from failure evidence.

No LLM. Dispatches to rule templates by trigger_type; all output is derivable from inputs.
"""

from __future__ import annotations

from oprim._aii_types import FailureLessonResult


_SUPPORTED_TYPES: frozenset[str] = frozenset(
    {"verify_failed", "retrieval_miss", "defeater_struck"}
)


def failure_lesson_extract(
    *,
    trigger_type: str,
    evidence: dict,
    subject_ref: str | None = None,
) -> FailureLessonResult:
    """Extract a deterministic failure lesson from structured evidence.

    Args:
        trigger_type: One of 'verify_failed', 'retrieval_miss', 'defeater_struck'.
        evidence: Field mapping specific to the trigger_type.
        subject_ref: Optional reference identifier for the subject.

    Returns:
        FailureLessonResult with lesson string and echo of inputs.

    Raises:
        ValueError: Unknown trigger_type or missing required evidence field.
    """
    if trigger_type not in _SUPPORTED_TYPES:
        raise ValueError(
            f"Unknown trigger_type {trigger_type!r}. "
            f"Supported: {sorted(_SUPPORTED_TYPES)}"
        )

    lesson: str

    if trigger_type == "verify_failed":
        lesson = _lesson_verify_failed(evidence)

    elif trigger_type == "retrieval_miss":
        if "query" not in evidence:
            raise ValueError(
                "trigger_type='retrieval_miss' requires 'query' in evidence"
            )
        lesson = f"主题 '{evidence['query']}' 检索无命中"

    else:  # defeater_struck
        if "contradicts_from" not in evidence:
            raise ValueError(
                "trigger_type='defeater_struck' requires 'contradicts_from' in evidence"
            )
        lesson = f"与已确证知识 {evidence['contradicts_from']} 矛盾"

    return FailureLessonResult(
        lesson=lesson,
        trigger_type=trigger_type,
        evidence=evidence,
        subject_ref=subject_ref,
    )


def _lesson_verify_failed(evidence: dict) -> str:
    """Dispatch verify_failed sub-rules; loogle_count==0 takes priority over sharpe."""
    has_loogle = "loogle_count" in evidence
    has_sharpe = "sharpe" in evidence

    if not has_loogle and not has_sharpe:
        raise ValueError(
            "trigger_type='verify_failed' requires 'loogle_count' or 'sharpe' in evidence"
        )

    if has_loogle and evidence["loogle_count"] == 0:
        return "非唯一命中，不可用此名确证"

    if has_sharpe:
        sharpe = float(evidence["sharpe"])
        return f"回测夏普 {sharpe:.2f}，未达显著性阈值"

    # loogle_count present but non-zero, sharpe absent
    raise ValueError(
        "trigger_type='verify_failed': loogle_count is non-zero; 'sharpe' required in evidence"
    )
