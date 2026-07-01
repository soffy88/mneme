"""未知席位模糊匹配审计循环 (oskill B10)."""

from __future__ import annotations

import oprim
import pandas as pd  # type: ignore[import-untyped]
from obase.audit import AuditEntry, format_audit_entry
from obase.text import fuzzy_match
from pydantic import BaseModel

from oskill._exceptions import OskillError


class UnknownSeatAuditResult(BaseModel):
    """未知席位审计结果摘要."""

    audit_entries: list[dict[str, object]]  # AuditEntry.model_dump() serialised
    high_risk_count: int
    total_observed: int
    matched_known: int


def unknown_seats_audit_loop(
    *,
    observed_seats: list[str],
    net_buys: list[float],
    known_tycoon_seats: list[str],
    match_threshold: float = 0.8,
    high_risk_net_buy_percentile: float = 75.0,
) -> UnknownSeatAuditResult:
    """Identify and audit unknown high-volume seats by fuzzy-matching against known list.

    Internal oprim composition:
    - oprim.percentile_rank    (ranks observed net-buy amounts to identify high-volume)
    - oprim.zscore_normalize   (normalises net-buy for anomaly scoring)

    obase composition:
    - obase.text.fuzzy_match        (soft-matches observed seats to known tycoon list)
    - obase.audit.format_audit_entry (creates auditable records for unrecognised seats)

    Args:
        observed_seats:                 Seat names active in today's LHB data.
        net_buys:                       Net buy amounts (万元) parallel to ``observed_seats``.
        known_tycoon_seats:             Reference list of confirmed hot-money seats.
        match_threshold:                Fuzzy match score (0.0–1.0) to consider a seat "known".
        high_risk_net_buy_percentile:   Percentile above which a seat is flagged high-risk.

    Returns:
        :class:`UnknownSeatAuditResult`.

    Raises:
        OskillError: If lengths differ or ``known_tycoon_seats`` is empty.

    Example:
        >>> seats = ["方正证券成都营业部", "某未知券商X"]
        >>> buys = [8000.0, 3000.0]
        >>> r = unknown_seats_audit_loop(seats, buys, known_tycoon_seats=["方正证券成都营业部"])
        >>> len(r.audit_entries) >= 0
        True
    """
    if len(observed_seats) != len(net_buys):
        raise OskillError("observed_seats and net_buys must have equal length")
    if not known_tycoon_seats:
        raise OskillError("known_tycoon_seats must not be empty")
    if not observed_seats:
        return UnknownSeatAuditResult(
            audit_entries=[], high_risk_count=0, total_observed=0, matched_known=0
        )

    nb_sr = pd.Series(net_buys, dtype=float)
    pct_ranks = oprim.percentile_rank(pd.DataFrame({"v": net_buys}), method="cross_sectional")[
        "v"
    ].tolist()
    z_scores = oprim.zscore_normalize(nb_sr, window=None, min_periods=1).fillna(0.0).tolist()

    entries: list[dict[str, object]] = []
    matched_count = 0
    high_risk = 0

    for i, seat in enumerate(observed_seats):
        matches = fuzzy_match(
            query=seat, candidates=known_tycoon_seats, threshold=match_threshold, top_k=1
        )
        is_known = len(matches) > 0
        if is_known:
            matched_count += 1
            continue

        is_high_risk = float(pct_ranks[i]) >= high_risk_net_buy_percentile
        if is_high_risk:
            high_risk += 1

        entry: AuditEntry = format_audit_entry(
            actor="system",
            action="flag_unknown_seat",
            resource_type="seat",
            resource_id=seat,
            detail={
                "net_buy_wan": net_buys[i],
                "percentile_rank": round(float(pct_ranks[i]), 2),
                "zscore": round(float(z_scores[i]), 4),
                "is_high_risk": is_high_risk,
            },
        )
        entries.append(entry.model_dump(mode="json"))

    return UnknownSeatAuditResult(
        audit_entries=entries,
        high_risk_count=high_risk,
        total_observed=len(observed_seats),
        matched_known=matched_count,
    )
