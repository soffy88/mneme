"""Retrieval evaluation harness (DeepTutor kb-eval method, clean rewrite).

Pure metric functions over rankings plus a thin live-scoring entry that
runs the SAME retrieval path a chat turn uses (search_knowledge_base).
Rankings are chunk ids, gold sets are chunk ids: that is what retrieval
actually returns (see knowledge_hub_search._row_to_result). There is no
KU-id mapping for chunks, so gold sets are chunk ids by design.

No model judges the output; metrics are pure functions over rankings.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

METRIC_KEYS = ("recall@k", "precision@k", "ndcg@k", "mrr", "map", "hit@k")


def _dcg(relevant: Sequence[int], k: int) -> float:
    return sum(1.0 / math.log2(rank + 1) for rank in relevant if rank <= k)


def score_ranking(ranked: Sequence[str], gold: set[str], k: int) -> dict[str, float]:
    """Score one ranking. Empty gold scores all zeros (documented)."""
    if k < 1:
        raise ValueError("k must be at least 1")
    top = list(ranked[:k])
    hits = [pos + 1 for pos, chunk_id in enumerate(top) if chunk_id in gold]
    n_hits = len(hits)
    n_gold = len(gold)
    recall = (n_hits / n_gold) if n_gold else 0.0
    precision = (n_hits / k) if k else 0.0
    ideal = _dcg(list(range(1, min(n_gold, k) + 1)), k)
    ndcg = (_dcg(hits, k) / ideal) if ideal > 0 else 0.0
    mrr = (1.0 / hits[0]) if hits else 0.0
    if n_gold and hits:
        precisions = [sum(1 for h in hits if h <= pos) / pos for pos in hits]
        average_precision = sum(precisions) / n_gold
    else:
        average_precision = 0.0
    return {
        "recall@k": recall,
        "precision@k": precision,
        "ndcg@k": ndcg,
        "mrr": mrr,
        "map": average_precision,
        "hit@k": 1.0 if hits else 0.0,
    }


def score_rankings(cases: Sequence[Mapping[str, Any]], k: int) -> dict[str, Any]:
    """Score offline cases {id, ranked, gold}; returns per-case + means."""
    scored: list[dict[str, Any]] = []
    for case in cases:
        ranked = list(case.get("ranked", []))
        gold = set(case.get("gold", []))
        scored.append(
            {
                "id": case.get("id"),
                "metrics": score_ranking(ranked, gold, k),
                "n_ranked": len(ranked),
                "n_gold": len(gold),
            }
        )
    aggregate = {
        key: (sum(s["metrics"][key] for s in scored) / len(scored)) if scored else 0.0
        for key in METRIC_KEYS
    }
    return {"k": k, "cases": scored, "aggregate": aggregate}


def eval_diff(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Per-metric deltas + per-case changes between two score_rankings runs."""
    base_by_id = {c["id"]: c["metrics"] for c in baseline.get("cases", [])}
    cand_by_id = {c["id"]: c["metrics"] for c in candidate.get("cases", [])}
    deltas = {
        key: float(candidate.get("aggregate", {}).get(key, 0.0)) - float(baseline.get("aggregate", {}).get(key, 0.0))
        for key in METRIC_KEYS
    }
    changed: list[dict[str, Any]] = []
    for case_id in sorted(set(base_by_id) | set(cand_by_id), key=str):
        base = base_by_id.get(case_id, {})
        cand = cand_by_id.get(case_id, {})
        case_deltas = {
            key: float(cand.get(key, 0.0)) - float(base.get(key, 0.0)) for key in METRIC_KEYS
        }
        if any(delta != 0.0 for delta in case_deltas.values()):
            changed.append({"id": case_id, "deltas": case_deltas})
    return {"metric_deltas": deltas, "changed_cases": changed}


async def score_retrieval(
    db: AsyncSession,
    qa_cases: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 5,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Run QA cases through the live retrieval path and score them.

    Cases that error are reported with an error flag and excluded from
    the aggregate means. Empty retrieval (empty KB, embedding down) is
    not an error: it scores zeros, honestly.
    """
    from services.knowledge_hub_search import search_knowledge_base

    scored: list[dict[str, Any]] = []
    for case in qa_cases:
        gold = set(case.get("gold", []))
        try:
            result = await search_knowledge_base(
                db, query=case.get("query", ""), top_k=top_k, min_score=min_score
            )
            ranked = [row.get("chunk_id") for row in result.get("results", [])]
            scored.append(
                {
                    "id": case.get("id"),
                    "metrics": score_ranking(ranked, gold, top_k),
                    "n_ranked": len(ranked),
                    "n_gold": len(gold),
                }
            )
        except Exception as exc:  # live path failure: report, do not poison means
            scored.append(
                {"id": case.get("id"), "error": str(exc), "metrics": None, "n_ranked": 0, "n_gold": len(gold)}
            )
    usable = [s for s in scored if s.get("metrics") is not None]
    aggregate = {
        key: (sum(s["metrics"][key] for s in usable) / len(usable)) if usable else 0.0
        for key in METRIC_KEYS
    }
    return {"k": top_k, "cases": scored, "aggregate": aggregate}


__all__ = ["METRIC_KEYS", "eval_diff", "score_ranking", "score_rankings", "score_retrieval"]
