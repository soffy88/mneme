"""概念主题 → 申万行业映射 (oprim B8)."""

from __future__ import annotations

from pydantic import BaseModel

from oprim._exceptions import OprimError


class ThemeSWMapping(BaseModel):
    """概念主题到申万行业的单条映射结果.

    Attributes:
        theme_name: 概念名称 (输入).
        sw_industry: 申万行业名称; ``None`` 表示未匹配.
        matched: 是否在 mapping_table 中找到精确匹配.
    """

    theme_name: str
    sw_industry: str | None
    matched: bool


def theme_to_sw_industry_mapping(
    *,
    theme_names: list[str],
    mapping_table: dict[str, str],
) -> list[ThemeSWMapping]:
    """Map concept-theme names to Shenwan (SW) industry classifications.

    Performs a direct lookup in the caller-supplied ``mapping_table``.
    The mapping table is injected rather than hardcoded so that callers
    can load it from DB, config file, or test fixtures.

    Args:
        theme_names:   List of concept names to look up.
        mapping_table: ``{theme_name: sw_industry}`` dict.  Keys must match
                       exactly (case-sensitive).

    Returns:
        One :class:`ThemeSWMapping` per input name, preserving order.
        ``matched=False`` and ``sw_industry=None`` when a name is absent.

    Raises:
        OprimError: If ``theme_names`` is empty.

    Example:
        >>> table = {"人工智能": "电子", "新能源汽车": "汽车"}
        >>> res = theme_to_sw_industry_mapping(theme_names=["人工智能", "区块链"], mapping_table=table)
        >>> res[0].sw_industry
        '电子'
        >>> res[1].matched
        False
    """
    if not theme_names:
        raise OprimError("theme_names must not be empty")
    return [
        ThemeSWMapping(
            theme_name=name,
            sw_industry=mapping_table.get(name),
            matched=name in mapping_table,
        )
        for name in theme_names
    ]
