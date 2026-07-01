"""oprim.keyword_alert_checker — Check text for keyword/regex pattern matches.

3O layer: oprim (single atomic pattern match, pure logic, no LLM).
Regex or exact-match scan of substrate text for configured alert keywords.
"""

from __future__ import annotations

import re


def keyword_alert_checker(
    *,
    text: str,
    keywords: list[str],
    mode: str = "exact",  # "exact" | "regex" | "fuzzy"
    case_sensitive: bool = False,
) -> dict:
    """Check text for keyword matches.

    Returns: {
        matches: [{keyword, positions: [int], count: int}],
        total_matches: int,
        has_alerts: bool,
        error: str|None,
    }
    """
    result: dict = {
        "matches": [],
        "total_matches": 0,
        "has_alerts": False,
        "error": None,
    }

    if not text or not keywords:
        return result

    search_text = text if case_sensitive else text.lower()
    match_list = []

    try:
        for keyword in keywords:
            search_kw = keyword if case_sensitive else keyword.lower()
            positions: list[int] = []

            if mode == "exact":
                start = 0
                while True:
                    idx = search_text.find(search_kw, start)
                    if idx == -1:
                        break
                    positions.append(idx)
                    start = idx + 1

            elif mode == "regex":
                flags = 0 if case_sensitive else re.IGNORECASE
                try:
                    for m in re.finditer(keyword, text, flags=flags):
                        positions.append(m.start())
                except re.error as exc:
                    result["error"] = f"invalid regex '{keyword}': {exc}"
                    return result

            elif mode == "fuzzy":
                # Simple fuzzy: edit distance ≤ 2 for short keywords (len ≤ 8)
                # Uses sliding window of same length as keyword
                kw_len = len(search_kw)
                if kw_len == 0:
                    continue
                for i in range(len(search_text) - kw_len + 1):
                    window = search_text[i : i + kw_len]
                    if _edit_distance(window, search_kw) <= 2:
                        positions.append(i)

            if positions:
                match_list.append(
                    {
                        "keyword": keyword,
                        "positions": positions,
                        "count": len(positions),
                    }
                )

        result["matches"] = match_list
        result["total_matches"] = sum(m["count"] for m in match_list)
        result["has_alerts"] = result["total_matches"] > 0

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]
