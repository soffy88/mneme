"""oprim.llm_extract_ku — single LLM call to extract a KU candidate from text.

3O layer: oprim (single LLM call, obase.ProviderRegistry, no state).
Produces default unverified KU candidate (A19: LLM proposes, never certifies).
"""

from __future__ import annotations

import json
import logging
import re
import uuid

_log = logging.getLogger(__name__)

_EXTRACT_PROMPT = """Extract a knowledge unit from the following text chunk.

Return JSON with these fields:
- knowledge_type: one of [proposition, rule, case, opinion, procedure, query, solution_strategy, relation, formula, theorem]
- natural_text: the key claim or knowledge in one clear sentence
- symbolic_form: structured representation (dict with type-specific fields, or null)
- tags: list of relevant keywords

Text:
{text}

Respond with valid JSON only."""

_RETRY_SUFFIX = "\n\nIMPORTANT: Respond with ONLY the JSON object. No explanation, no markdown, no code fences."


def _parse_json_response(resp: str) -> dict:
    """Strip markdown fences and parse JSON. Raises json.JSONDecodeError on failure."""
    t = resp.strip()
    t = re.sub(r'^```(?:json)?\s*\n?', '', t)
    t = re.sub(r'\n?```\s*$', '', t).strip()
    return json.loads(t)


def llm_extract_ku(
    *,
    text: str,
    project_id: str = "default",
    knowledge_type_hint: str | None = None,
    provider: str = "default",
) -> dict:
    """Extract a KU candidate from text via single LLM call.

    On JSON parse failure: retries once with explicit JSON-only instruction.
    On second failure: returns KU with empty knowledge_type so ku_gate_validate rejects it
    (residue not stored, consistent with §: 残品不入库).

    On ProviderNotFoundError/RuntimeError (LLM unavailable): falls back to deterministic stub.

    Returns KU dict with epistemic_status.verified=False (A19: default unverified).
    """
    _raw = None
    _provider_unavailable = False

    try:
        from obase import ProviderRegistry
        from obase.exceptions import ProviderNotFoundError

        llm = ProviderRegistry.get().llm(provider)
        # Prefer sync wrapper (async LLMs attach call_sync)
        caller = getattr(llm, 'call_sync', None) or llm
        prompt = _EXTRACT_PROMPT.format(text=text[:3000])

        response = caller(prompt)
        try:
            _raw = _parse_json_response(response)
        except json.JSONDecodeError:
            # Retry once with explicit JSON-only instruction
            response2 = caller(prompt + _RETRY_SUFFIX)
            try:
                _raw = _parse_json_response(response2)
            except json.JSONDecodeError as e:
                _log.warning("llm_extract_ku: non-JSON after retry (%s), chunk discarded", e)
                # _raw stays None → knowledge_type will be "" → gate rejects

    except (ProviderNotFoundError, RuntimeError):
        _log.warning(
            "llm_extract_ku: LLM provider %r not registered — falling back to stub", provider
        )
        _provider_unavailable = True
    except ImportError:
        _provider_unavailable = True

    # Build result fields
    if _raw is not None:
        knowledge_type = _raw.get("knowledge_type", "proposition")
        natural_text = _raw.get("natural_text", text[:200])
        symbolic_form = _raw.get("symbolic_form")
        tags = _raw.get("tags", [])
    elif _provider_unavailable:
        # LLM unavailable: deterministic stub (first sentence)
        natural_text = text.split(".")[0].strip()[:200] or text[:200]
        knowledge_type = knowledge_type_hint or "proposition"
        symbolic_form = None
        tags = []
    else:
        # JSON failed after retry: produce invalid KU → gate rejects → not stored
        natural_text = ""
        knowledge_type = ""
        symbolic_form = None
        tags = []

    return {
        "ku_id": str(uuid.uuid4()),
        "knowledge_type": knowledge_type,
        "natural_text": natural_text,
        "symbolic_form": symbolic_form,
        "vector": None,
        "vector_frozen": False,
        "epistemic_status": {
            "grade": "unverified",
            "source": None,
            "defeaters": [],
            "verified": False,  # A19: LLM proposal, default unverified
        },
        "provenance": {"source": "llm_extract", "chunk_id": None},
        "project_id": project_id,
        "tags": tags,
    }
