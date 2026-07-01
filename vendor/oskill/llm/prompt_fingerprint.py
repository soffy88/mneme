"""Deterministic prompt fingerprint (audit / caching / A/B testing)."""

from __future__ import annotations

from typing import Any

from oprim import canonical_json, sha256_hash


def prompt_fingerprint(
    prompt_template: str,
    variables: dict[str, Any] | None = None,
    *,
    model: str | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Compute deterministic fingerprint for a prompt configuration.

    Workflow (2 oprim calls):
        1. oprim.sha256_hash(prompt_template) → template_fingerprint
        2. oprim.canonical_json(full_payload) + oprim.sha256_hash → fingerprint

    Returns dict with keys:
        - 'fingerprint': SHA-256 hex (64 chars) of canonical(all_inputs)
        - 'template_fingerprint': hash of just template (independent of variables)
        - 'full_payload_canonical': canonical JSON string of all inputs

    Use cases:
        - Audit: prove a decision used specific prompt + variables
        - Caching: lookup by fingerprint
        - A/B testing: compare strategies by prompt version
        - Cross-session reproducibility: same fingerprint → same prompt

    Note: None values for model/temperature/seed are included in canonical payload
    (as JSON null). empty dict and None for variables/extra are treated identically.
    Integer and float representations produce different fingerprints (e.g. seed=1
    vs seed=1.0); callers must be consistent.

    Reference: arxiv 2601.15322 (Replayable Financial Agents, 2026).

    Parameters
    ----------
    prompt_template : str
        Prompt template string (may contain {variable} placeholders).
    variables : dict or None
        Template variable values. None and {} produce the same fingerprint.
    model : str or None
        Model identifier (included in fingerprint).
    temperature : float or None
        Sampling temperature (included in fingerprint).
    seed : int or None
        Random seed (included in fingerprint).
    extra : dict or None
        Additional metadata to include in fingerprint.

    Returns
    -------
    dict with 'fingerprint', 'template_fingerprint', 'full_payload_canonical'.
    """
    # 1. Template fingerprint (oprim call 1)
    template_fp = sha256_hash(prompt_template)

    # 2. Full payload fingerprint (oprim calls 2 + 3)
    payload: dict[str, Any] = {
        "template": prompt_template,
        "variables": variables if variables is not None else {},
        "model": model,
        "temperature": temperature,
        "seed": seed,
        "extra": extra if extra is not None else {},
    }
    canonical_str = canonical_json(payload)
    full_fp = sha256_hash(canonical_str)

    return {
        "fingerprint": full_fp,
        "template_fingerprint": template_fp,
        "full_payload_canonical": canonical_str,
    }
