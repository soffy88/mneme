"""Auto-split from hicode whl."""

from __future__ import annotations
from ._exceptions import SearchOprimError
from ._protocols import SearchCaller
from .llm._types import SearchResult

async def web_search(
    query: str,
    *,
    client: SearchCaller,
    top_k: int = 5,
) -> list[SearchResult]:
    """单次 Web 搜索，返回结构化结果列表。

    Args:
        query: 搜索查询字符串。
        client: SearchCaller Protocol 实例（由调用方注入）。
        top_k: 返回结果数量上限，默认 5。

    Returns:
        SearchResult 列表（按相关性排序）。

    Raises:
        SearchOprimError: 查询为空或搜索调用失败。

    Example:
        >>> results = await web_search("python asyncio tutorial", client=searcher)
        >>> results[0].title
        'Asyncio — Python 3.12 docs'
    """
    if not query or not query.strip():
        raise SearchOprimError("web_search: query must not be empty")

    try:
        raw = await client(query=query, top_k=top_k)
    except (SearchOprimError,):
        raise  # pragma: no cover
    except Exception as e:
        raise SearchOprimError("web_search call failed", cause=e)

    results = []
    for i, item in enumerate(raw[:top_k]):
        if not isinstance(item, dict):
            continue
        results.append(SearchResult(
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            snippet=str(item.get("snippet", item.get("description", ""))),
            rank=i,
        ))
    return results
