"""合规免责声明注入 (oprim B8)."""

from __future__ import annotations

from typing import Literal

from oprim._exceptions import OprimError

DISCLAIMER = "本内容仅供信息参考，不构成投资建议。"

_SEP = "\n\n"


def compliance_disclaimer_inject(
    *,
    text: str,
    position: Literal["prefix", "suffix", "both"] = "suffix",
    disclaimer: str = DISCLAIMER,
) -> str:
    """Inject a compliance disclaimer into a text string.

    Args:
        text:       Source text to annotate.
        position:   Where to insert the disclaimer:
                    - ``"prefix"`` — prepend before ``text``
                    - ``"suffix"`` — append after ``text`` (default)
                    - ``"both"``   — prepend and append
        disclaimer: Override the disclaimer text.  Defaults to the standard
                    ``"本内容仅供信息参考，不构成投资建议。"``.

    Returns:
        Annotated string.

    Raises:
        OprimError: If ``position`` is not one of the allowed values.

    Example:
        >>> s = compliance_disclaimer_inject(text="买入 600519")
        >>> s.endswith("不构成投资建议。")
        True
        >>> s2 = compliance_disclaimer_inject(text="报告内容", position="prefix")
        >>> s2.startswith("本内容仅供信息参考")
        True
    """
    if position not in ("prefix", "suffix", "both"):
        raise OprimError(f"position must be 'prefix'/'suffix'/'both', got {position!r}")
    if position == "prefix":
        return disclaimer + _SEP + text
    if position == "suffix":
        return text + _SEP + disclaimer
    return disclaimer + _SEP + text + _SEP + disclaimer
