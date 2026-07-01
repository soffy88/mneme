from __future__ import annotations

from typing import Any

from oprim._exceptions import OprimError
from oprim.llm_judge_rerank import LLMCaller


def llm_query_expand(
    *,
    query: str,
    llm: LLMCaller,
    num_variants: int = 3,
) -> list[str]:
    """使用 LLM 扩展查询.

    Args:
        query: 原始查询
        llm: LLM 调用函数
        num_variants: 需要生成的变体数量

    Returns:
        包含 [原始查询] + [变体] 的列表

    Raises:
        OprimError: 如果 query 为空或 num_variants <= 0

    Example:
        ```python
        def dummy_llm(**kwargs):
            return {"content": "var 1\\nvar 2"}
        
        variants = llm_query_expand(query="test", llm=dummy_llm, num_variants=2)
        assert len(variants) == 3
        assert variants[0] == "test"
        ```
    """
    if not query.strip():
        raise OprimError("Query cannot be empty")
    
    if num_variants <= 0:
        raise OprimError("num_variants must be > 0")

    prompt = f"""Please generate {num_variants} alternative search queries for the following query.
The alternatives should use different vocabulary, synonyms, or related concepts to help find relevant documents.

Original query: {query}

Output ONLY the alternative queries, one per line. Do NOT output numbering, bullets, or any other text.
"""

    messages = [{"role": "user", "content": prompt}]
    
    try:
        response = llm(messages=messages)
        content = response.get("content", "")
    except Exception:
        # Fallback
        return [query]

    # Parse response
    lines = [line.strip() for line in content.split("\n")]
    lines = [line for line in lines if line]
    
    # Remove numbering if LLM ignored instructions (e.g. "1. xxx")
    cleaned_lines = []
    import re
    for line in lines:
        cleaned_line = re.sub(r"^\d+[\.\)\]]\s*", "", line).strip()
        cleaned_line = re.sub(r"^-\s*", "", cleaned_line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    # Pad or truncate
    if len(cleaned_lines) > num_variants:
        cleaned_lines = cleaned_lines[:num_variants]
    elif len(cleaned_lines) < num_variants:
        # Just duplicate the query to fill
        while len(cleaned_lines) < num_variants:
            cleaned_lines.append(query)

    return [query] + cleaned_lines
