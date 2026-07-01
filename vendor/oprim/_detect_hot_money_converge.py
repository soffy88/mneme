"""游资集中检测 — 知名游资席位命中 + 净买入超阈值 (oprim B9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError


class HotMoneyConvergeConfig(BaseModel):
    """游资集中检测阈值配置.

    Attributes:
        min_seat_hits: 命中知名游资席位的最少数量.
        min_net_buy:   净买入金额下限 (万元).
    """

    min_seat_hits: int = Field(default=2, ge=1)
    min_net_buy: float = Field(default=5000.0, gt=0)


def detect_hot_money_converge(
    *,
    seat_names: list[str],
    net_buy_total: float,
    known_tycoon_seats: list[str],
    config: HotMoneyConvergeConfig = HotMoneyConvergeConfig(),
) -> DetectorSignal | None:
    """Detect hot money (游资) convergence on a single stock.

    Triggers when:
    - Number of seats in ``seat_names`` that appear in ``known_tycoon_seats``
      ≥ ``config.min_seat_hits``
    - ``net_buy_total ≥ config.min_net_buy``

    The ``known_tycoon_seats`` list is caller-injected so the detector stays pure
    and testable without hardcoded data.

    Args:
        seat_names:         Active brokerage seats appearing in today's LHB data.
        net_buy_total:      Net buy amount across all seats (万元).
        known_tycoon_seats: Reference list of known hot-money seat names.
        config:             Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If ``known_tycoon_seats`` is empty.

    Example:
        >>> known = ["方正证券成都营业部", "国泰君安上海分公司"]
        >>> sig = detect_hot_money_converge(
        ...     seat_names=["方正证券成都营业部", "招商证券深圳分公司", "国泰君安上海分公司"],
        ...     net_buy_total=8000.0,
        ...     known_tycoon_seats=known,
        ... )
        >>> sig is not None
        True
    """
    if not known_tycoon_seats:
        raise OprimError("known_tycoon_seats must not be empty")

    known_set = set(known_tycoon_seats)
    matched = [s for s in seat_names if s in known_set]
    hit_count = len(matched)

    if hit_count < config.min_seat_hits or net_buy_total < config.min_net_buy:
        return None

    severity = "high" if hit_count >= config.min_seat_hits * 2 else "medium"

    return DetectorSignal(
        detector_name="hot_money_converge",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "matched_seats": matched,
            "hit_count": hit_count,
            "net_buy_total_wan": net_buy_total,
            "known_seats_checked": len(known_tycoon_seats),
        },
    )
