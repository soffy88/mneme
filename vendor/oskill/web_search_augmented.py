"""oskill.web_search_augmented — Web search with graph-augmented result ranking.

3O layer: oskill (≥2 oprim composition, stateless).
Note: Requires searxng deployment for live search. Stub mode in test environments.

Internal oprim composition:
    - oprim.url_fetch_ssrf_safe: SSRF-safe fetch of searxng results
    - oprim.bm25_search: re-rank results by query relevance
    - oprim.graph_traversal: expand result context via concept graph
"""

from __future__ import annotations

import json

from oprim import bm25_search, graph_traversal, url_fetch_ssrf_safe


def web_search_augmented(
    *,
    query: str,
    searxng_url: str = "",  # empty = stub mode
    max_results: int = 10,
    rerank: bool = True,
) -> dict:
    """Search web via searxng and augment results with BM25 re-ranking.

    When searxng_url is empty or unreachable, returns stub mode with empty
    results. When a valid searxng endpoint is provided, fetches JSON results
    via url_fetch_ssrf_safe and re-ranks snippets via bm25_search.

    Internal oprim composition:
        url_fetch_ssrf_safe issues SSRF-protected HTTP GET to searxng.
        bm25_search re-ranks result snippets by BM25 score against query.
        graph_traversal expands result set when a concept graph is available
        (currently stub: no-op traversal from result node ids).

    Note: Requires searxng deployment to be activated. Stub returns empty
    results when searxng_url is empty or unavailable.

    Returns: {
        results: [{"title": str, "url": str, "snippet": str, "score": float}],
        query: str,
        total: int,
        provider: str,  # "searxng" | "stub"
        error: str | None,
    }
    """
    result: dict = {
        "results": [],
        "query": query,
        "total": 0,
        "provider": "stub",
        "error": None,
    }

    # Stub mode: no searxng URL configured
    if not searxng_url:
        return result

    # 1. Fetch searxng JSON results via url_fetch_ssrf_safe
    search_endpoint = searxng_url.rstrip("/") + "/search"
    import urllib.parse

    params = urllib.parse.urlencode({"q": query, "format": "json"})
    full_url = f"{search_endpoint}?{params}"

    fetch_result = url_fetch_ssrf_safe(url=full_url, timeout=10)
    if fetch_result.get("error"):
        result["error"] = fetch_result["error"]
        return result

    # 2. Parse JSON results
    try:
        body_text = fetch_result.get("body_text") or ""
        data = json.loads(body_text)
        raw_results = data.get("results", [])
    except Exception as exc:
        result["error"] = f"json_parse_error: {exc}"
        return result

    # Normalise results
    items: list[dict] = []
    for item in raw_results[:max_results]:
        items.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "score": float(item.get("score", 0.0)),
            }
        )

    # 3. BM25 re-ranking of snippets
    if rerank and items:
        docs = {str(i): (it["title"] + " " + it["snippet"]) for i, it in enumerate(items)}
        bm25_hits = bm25_search(query=query, docs=docs, top_k=len(items))
        # Apply BM25 scores; items not in hits get score 0.0
        bm25_score_map = {doc_id: score for doc_id, score in bm25_hits}
        reranked: list[dict] = []
        for i, it in enumerate(items):
            it = dict(it)
            it["score"] = bm25_score_map.get(str(i), 0.0)
            reranked.append(it)
        reranked.sort(key=lambda x: -x["score"])
        items = reranked[:max_results]

    # 4. Graph traversal (concept expansion stub — no-op when no graph provided)
    _concept_expand_stub(items=items, query=query)

    result["results"] = items
    result["total"] = len(items)
    result["provider"] = "searxng"
    return result


def _concept_expand_stub(*, items: list[dict], query: str) -> None:
    """Stub concept graph expansion via graph_traversal.

    In production, this would use a concept graph to expand result nodes.
    Currently performs a no-op traversal from result URL nodes.
    """
    if not items:
        return
    start_nodes = [it["url"] for it in items if it.get("url")]
    graph_traversal(
        start_nodes=start_nodes[:5],
        get_neighbors=lambda node: [],  # no graph edges in stub
        mode="bfs",
        max_depth=1,
        max_nodes=10,
    )
