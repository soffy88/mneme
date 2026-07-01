"""板块塌方检测 — 1H 跌幅 + 内部分化 (oprim B9)."""

from __future__ import annotations

import statistics

from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError


class SectorCollapseConfig(BaseModel):
    """板块塌方检测阈值配置.

    Attributes:
        drop_threshold_1h:        触发所需的 1H 跌幅上限 (负数, 如 -0.03 表示跌 3%).
        divergence_std_threshold: 成分股涨跌幅标准差下限 (如 0.05 表示 5%).
    """

    drop_threshold_1h: float = Field(default=-0.03, le=0)
    divergence_std_threshold: float = Field(default=0.05, ge=0)


def detect_sector_collapse(
    *,
    price_1h_ago: float,
    price_now: float,
    constituent_changes: list[float],
    config: SectorCollapseConfig = SectorCollapseConfig(),
) -> DetectorSignal | None:
    """Detect a sector-wide collapse: sharp 1H drop with elevated internal divergence.

    Triggers when:
    - ``(price_now − price_1h_ago) / price_1h_ago < config.drop_threshold_1h``
    - ``stdev(constituent_changes) > config.divergence_std_threshold``

    Args:
        price_1h_ago:         Sector index price 1 hour ago.
        price_now:            Current sector index price.
        constituent_changes:  List of individual stock change % (e.g. 0.02 = +2 %).
                              Must have ≥ 2 elements.
        config:               Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If ``price_1h_ago`` ≤ 0 or fewer than 2 constituents supplied.

    Example:
        >>> cfg = SectorCollapseConfig(drop_threshold_1h=-0.02, divergence_std_threshold=0.03)
        >>> sig = detect_sector_collapse(
        ...     price_1h_ago=100.0, price_now=97.5,
        ...     constituent_changes=[-0.05, 0.02, -0.04, 0.03],
        ...     config=cfg,
        ... )
        >>> sig is not None and sig.severity in ("medium", "high", "critical")
        True
    """
    if price_1h_ago <= 0:
        raise OprimError(f"price_1h_ago must be > 0, got {price_1h_ago}")
    if len(constituent_changes) < 2:
        raise OprimError(
            f"constituent_changes must have ≥ 2 elements, got {len(constituent_changes)}"
        )

    drop_1h = (price_now - price_1h_ago) / price_1h_ago
    div_std = statistics.stdev(constituent_changes)

    if drop_1h >= config.drop_threshold_1h or div_std <= config.divergence_std_threshold:
        return None

    if drop_1h < config.drop_threshold_1h * 1.5 and div_std > config.divergence_std_threshold * 1.5:
        severity = "critical"
    elif drop_1h < config.drop_threshold_1h * 1.2:
        severity = "high"
    else:
        severity = "medium"

    return DetectorSignal(
        detector_name="sector_collapse",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "drop_1h": round(drop_1h, 6),
            "divergence_std": round(div_std, 6),
            "constituent_count": len(constituent_changes),
            "thresholds": {
                "drop": config.drop_threshold_1h,
                "std": config.divergence_std_threshold,
            },
        },
    )
