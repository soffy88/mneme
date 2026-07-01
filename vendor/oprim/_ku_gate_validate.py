"""oprim.ku_gate_validate — KU pre-storage gate validation.

3O layer: oprim (single atomic validation call, pure logic, no LLM).
Validates a KU candidate against HOS-001 three-face-unity schema.
Returns validation result — caller decides: pass→storage, fail→quarantine.
"""

from __future__ import annotations

REASONING_TYPES = {"theorem", "rule", "formula"}
VALID_KNOWLEDGE_TYPES = {
    "proposition",
    "relation",
    "rule",
    "formula",
    "theorem",
    "case",
    "opinion",
    "procedure",
    "query",
    "solution_strategy",
}
VALID_GRADES = {"unverified", "low", "moderate", "high", "proven"}


def ku_gate_validate(
    *,
    ku: dict,
) -> dict:
    """Validate a KU candidate against HOS-001 schema.

    Returns: {valid: bool, errors: list[str], warnings: list[str]}
    Errors → reject (quarantine). Warnings → log but allow.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # natural_text required
    natural_text = ku.get("natural_text")
    if not natural_text or not str(natural_text).strip():
        errors.append("natural_text is required and must be non-empty")

    # knowledge_type required and valid
    knowledge_type = ku.get("knowledge_type")
    if not knowledge_type:
        errors.append("knowledge_type is required")
    elif knowledge_type not in VALID_KNOWLEDGE_TYPES:
        errors.append(
            f"knowledge_type '{knowledge_type}' is invalid; "
            f"must be one of {sorted(VALID_KNOWLEDGE_TYPES)}"
        )

    # epistemic_status required
    epistemic_status = ku.get("epistemic_status")
    if not epistemic_status or not isinstance(epistemic_status, dict):
        errors.append("epistemic_status is required and must be a dict")
    else:
        grade = epistemic_status.get("grade")
        if not grade:
            errors.append("epistemic_status.grade is required")
        elif grade not in VALID_GRADES:
            errors.append(
                f"epistemic_status.grade '{grade}' is invalid; "
                f"must be one of {sorted(VALID_GRADES)}"
            )

    # symbolic_form required for reasoning types (only if knowledge_type is valid)
    if knowledge_type and knowledge_type in REASONING_TYPES:
        symbolic_form = ku.get("symbolic_form")
        if symbolic_form is None:
            errors.append(
                f"symbolic_form is required for knowledge_type '{knowledge_type}' (reasoning type)"
            )

    # project_id should be non-empty — warning if missing
    project_id = ku.get("project_id")
    if not project_id or not str(project_id).strip():
        warnings.append("project_id is missing or empty; KU will be orphaned")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
