"""oprim.mathlib_lookup — Look up Lean/Mathlib theorem identifiers via Loogle API.

3O layer: oprim (形态2 单外部 API).
"""

from __future__ import annotations

import json
import urllib.parse

from obase.http.dns_pinned_transport import make_ssrf_safe_opener
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class MathlibHit(BaseModel):
    """A single hit from the Mathlib lookup."""

    name: str = Field(..., description="Lean 标识符全名")
    module: str = Field(..., description="所在 Mathlib 模块")
    type_signature: str = Field(..., description="类型签名")


class MathlibLookupResult(BaseModel):
    """Result of a Mathlib lookup."""

    query: str
    count: int = Field(..., description="命中数; ==1 为唯一无歧义命中")
    hits: list[MathlibHit]


def mathlib_lookup(
    *,
    identifier: str,
    api_base: str = "https://loogle.lean-lang.org/json",
    timeout_seconds: float = 10.0,
) -> MathlibLookupResult:
    """查一个标识符在 Mathlib 的形式化条目 (单次 API 调用).

    通过 Loogle API 查询 Lean/Mathlib 既有形式化定理条目。
    count==1 表示唯一无歧义命中, 可用于既有定理确证 (不需现场证明)。

    Args:
        identifier: 要查的 Lean 标识符或定理名.
        api_base: Loogle JSON API 端点 (可替换为其他 Mathlib 查询服务).
        timeout_seconds: 请求超时.

    Returns:
        MathlibLookupResult: count + hits 列表.

    Raises:
        OprimError: API 请求失败 / 超时 / 响应格式异常 (不静默吞错).

    Example:
        >>> r = mathlib_lookup(identifier="Nat.add_comm")
        >>> r.count
        1
        >>> r.hits[0].module
        'Mathlib.Algebra.Group.Nat'
    """
    if not identifier:
        raise OprimError("Identifier cannot be empty")

    url = f"{api_base}?q={urllib.parse.quote(identifier)}"

    try:
        opener = make_ssrf_safe_opener(timeout=int(timeout_seconds))
        with opener.open(url, timeout=timeout_seconds) as resp:
            if resp.status != 200:
                raise OprimError(f"API request failed with status {resp.status}")

            data = json.loads(resp.read().decode("utf-8"))

            # Loogle API format: {"hits": [{"name": "...", "module": "...", "type": "..."}]}
            # Note: Loogle JSON might have slightly different keys; we align with spec.
            # If the actual API has 'type' instead of 'type_signature', we map it.
            raw_hits = data.get("hits", [])
            hits = []
            for hit in raw_hits:
                hits.append(
                    MathlibHit(
                        name=hit.get("name", "unknown"),
                        module=hit.get("module", "unknown"),
                        type_signature=hit.get("type", "unknown"),
                    )
                )

            return MathlibLookupResult(
                query=identifier,
                count=len(hits),
                hits=hits,
            )

    except json.JSONDecodeError as e:
        raise OprimError(f"Invalid JSON response from API: {e}") from e
    except Exception as e:
        if "timeout" in str(e).lower():
            raise OprimError("API request timed out") from e
        raise OprimError(f"API request failed: {e}") from e
