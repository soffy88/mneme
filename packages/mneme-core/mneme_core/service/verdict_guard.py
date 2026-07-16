"""verdict_guard — P2 guardrail enforcement. Called BEFORE any write to core-db.
Violations raise GuardRejection (HTTP 422). NEVER writes to DB on violation."""
from __future__ import annotations


class GuardRejection(Exception):
    """Raised when a verdict fails guardrail checks. Results in HTTP 422."""
    pass


def enforce(
    verdict_source: str,
    evidence_ref: str | None,
    *,
    origin: str = "core",  # "core" or "agent"
) -> None:
    """Validate verdict before core-db write. Raises GuardRejection on violation.

    Rules:
    1. verdict_source must be "deterministic" or "llm_verified"
    2. llm_verified MUST have non-empty evidence_ref
    3. agent origin CANNOT claim deterministic (prevents agent forging)
    """
    if verdict_source not in ("deterministic", "llm_verified"):
        raise GuardRejection(
            f"verdict_source must be 'deterministic' or 'llm_verified', got '{verdict_source}'"
        )

    if verdict_source == "llm_verified" and not evidence_ref:
        raise GuardRejection("llm_verified verdict MUST include evidence_ref")

    if origin == "agent" and verdict_source == "deterministic":
        raise GuardRejection(
            "agent origin cannot claim deterministic verdict — only core grading_service can"
        )
