"""配置驱动券商导出渲染 (oprim B8)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from oprim._exceptions import OprimError


class BrokerExportResult(BaseModel):
    """券商导出渲染结果.

    Attributes:
        content:     导出内容 (CSV/TSV 文本或 JSON 字符串).
        format:      格式标识 — ``"csv"`` / ``"tsv"`` / ``"json"``.
        row_count:   数据行数 (不含表头).
        broker_name: 券商名称.
    """

    content: str
    format: str
    row_count: int
    broker_name: str


def broker_export_render(
    *,
    broker_name: str,
    template_config: dict[str, Any],
    order_data: list[dict[str, Any]],
) -> BrokerExportResult:
    """Render order data into a broker-specific export format.

    ``template_config`` drives the output:
    - ``"format"`` (str): ``"csv"``, ``"tsv"``, or ``"json"``.  Defaults to ``"csv"``.
    - ``"columns"`` (list[str]): ordered column names to include.  If absent, all
      keys from the first order row are used.
    - ``"delimiter"`` (str): column separator for CSV/TSV.  Defaults to ``","`` for CSV
      and ``"\\t"`` for TSV.
    - ``"header"`` (bool): whether to include a header row.  Defaults to ``True``.

    Args:
        broker_name:      Human-readable broker identifier (e.g. ``"华泰证券"``).
        template_config:  Export template parameters (see above).
        order_data:       List of order dicts.  May be empty.

    Returns:
        :class:`BrokerExportResult`.

    Raises:
        OprimError: If ``format`` is unsupported or ``columns`` references
                    missing keys.

    Example:
        >>> cfg = {"format": "csv", "columns": ["symbol", "qty", "price"]}
        >>> orders = [{"symbol": "600519", "qty": 100, "price": 1800.0}]
        >>> r = broker_export_render(broker_name="华泰", template_config=cfg, order_data=orders)
        >>> "600519" in r.content
        True
    """
    fmt = str(template_config.get("format", "csv")).lower()
    if fmt not in ("csv", "tsv", "json"):
        raise OprimError(f"Unsupported format {fmt!r}; choose csv/tsv/json")

    if fmt == "json":
        import json

        content = json.dumps(order_data, ensure_ascii=False, indent=2)
        return BrokerExportResult(
            content=content, format=fmt, row_count=len(order_data), broker_name=broker_name
        )

    columns: list[str] = list(
        template_config.get("columns") or (order_data[0].keys() if order_data else [])
    )
    for col in columns:
        for row in order_data:
            if col not in row:
                raise OprimError(f"Column {col!r} not found in order_data rows")

    delimiter = str(template_config.get("delimiter") or ("," if fmt == "csv" else "\t"))
    include_header = bool(template_config.get("header", True))

    lines: list[str] = []
    if include_header:
        lines.append(delimiter.join(columns))
    for row in order_data:
        lines.append(delimiter.join(str(row.get(c, "")) for c in columns))

    return BrokerExportResult(
        content="\n".join(lines),
        format=fmt,
        row_count=len(order_data),
        broker_name=broker_name,
    )
