"""P-AII-3: relation_extract_rule — pure-rule relation extraction from KU text.

No LLM, fully deterministic. Rule set:
  - 定理引用 ("由X定理"/"X引理"/"根据X定理") → references
  - 符号依赖 (ku_symbolic refs known symbols)  → prerequisite_of
  - 特例句式 ("是X的特例"/"退化为X")           → special_case_of
  - 矛盾句式 ("与X矛盾"/"否定了X")             → contradicts
  - 无匹配                                      → []
"""
from __future__ import annotations

import re

from oprim._aii_graph_types import RelationCandidate

# --- Theorem reference patterns (with explicit Chinese keywords) ---
_THEOREM_PAT = re.compile(
    r'(?:由|根据|依据|见|利用|引用)\s*'
    r'([^\s，。；！？\n（(]{1,30}?)\s*'
    r'(?:定理|引理|公理|命题|推论|定律)',
    re.UNICODE,
)

# --- Special case sentence patterns ---
_SPECIAL_PAT = re.compile(
    r'是\s*([^\s，。；！？\n（(]{1,30}?)\s*的\s*(?:特例|特殊(?:情况|形式|版本))'
    r'|退化为\s*([^\s，。；！？\n（(]{1,30})'
    r'|当.{0,40}?时\s*退化为\s*([^\s，。；！？\n（(]{1,30})',
    re.UNICODE,
)

# --- Contradiction sentence patterns ---
_CONTRADICT_PAT = re.compile(
    r'与\s*([^\s，。；！？\n（(]{1,30}?)\s*(?:矛盾|相矛盾|对立|冲突)'
    r'|否定了\s*([^\s，。；！？\n（(]{1,30})'
    r'|反驳了\s*([^\s，。；！？\n（(]{1,30})',
    re.UNICODE,
)


def _resolve_entity(
    raw: str,
    known_entities: list[str] | None,
) -> tuple[str, str]:
    """Return (target_ref, confidence_signal) after cross-checking known_entities."""
    if known_entities is None:
        return raw, "rule_match"
    exact = [e for e in known_entities if e == raw]
    if exact:
        return exact[0], "rule_match"
    partial = [e for e in known_entities if raw in e or e in raw]
    if len(partial) == 1:
        return partial[0], "rule_match"
    if len(partial) > 1:
        return raw, "ambiguous"
    return raw, "rule_match"


def _collect_symbols(ku_symbolic: dict) -> list[str]:
    syms: list[str] = []
    for v in ku_symbolic.values():
        if isinstance(v, str):
            syms.append(v)
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    syms.append(item)
    return syms


def relation_extract_rule(
    *,
    ku_text: str,
    ku_symbolic: dict | None = None,
    known_entities: list[str] | None = None,
) -> list[RelationCandidate]:
    """Extract relation candidates from a KU using rule-based patterns.

    Returns [] for empty text or no matches.  known_entities=None skips
    symbol-dependency matching and ambiguity resolution.
    """
    if not ku_text.strip():
        return []

    results: list[RelationCandidate] = []
    seen_evidence: set[str] = set()

    # --- Theorem references ---
    for m in _THEOREM_PAT.finditer(ku_text):
        raw = m.group(1).strip()
        if not raw:
            continue
        target, sig = _resolve_entity(raw, known_entities)
        key = ("references", target)
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        results.append(RelationCandidate(
            relation_type="references",
            target_ref=target,
            evidence=m.group(0).strip(),
            confidence_signal=sig,
        ))

    # --- Special case sentences ---
    for m in _SPECIAL_PAT.finditer(ku_text):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        raw = raw.strip()
        target, sig = _resolve_entity(raw, known_entities)
        key = ("special_case_of", target)
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        results.append(RelationCandidate(
            relation_type="special_case_of",
            target_ref=target,
            evidence=m.group(0).strip(),
            confidence_signal=sig,
        ))

    # --- Contradiction sentences ---
    for m in _CONTRADICT_PAT.finditer(ku_text):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        raw = raw.strip()
        target, sig = _resolve_entity(raw, known_entities)
        key = ("contradicts", target)
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        results.append(RelationCandidate(
            relation_type="contradicts",
            target_ref=target,
            evidence=m.group(0).strip(),
            confidence_signal=sig,
        ))

    # --- Symbol dependencies (only when known_entities provided) ---
    if ku_symbolic is not None and known_entities is not None:
        for sym in _collect_symbols(ku_symbolic):
            if sym in known_entities:
                key = ("prerequisite_of", sym)
                if key in seen_evidence:
                    continue
                seen_evidence.add(key)
                results.append(RelationCandidate(
                    relation_type="prerequisite_of",
                    target_ref=sym,
                    evidence=f"symbol dependency: {sym!r}",
                    confidence_signal="symbol_dep",
                ))

    return results
