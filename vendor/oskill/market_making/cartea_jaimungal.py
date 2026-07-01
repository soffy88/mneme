"""Cartea-Jaimungal extensions to the Avellaneda-Stoikov market making model."""

from __future__ import annotations

from typing import Any

import oprim

from oskill.market_making._base import _as_optimal_spread, _as_reservation_price


def cartea_jaimungal_optimal_quotes(
    mid_price: float,
    inventory: int,
    order_flow_imbalance: float,
    *,
    volatility: float,
    drift: float = 0.0,
    time_to_horizon: float = 1.0,
    risk_aversion: float = 0.1,
    inventory_penalty: float = 0.01,
    adverse_selection_aversion: float = 0.5,
    intensity_k: float = 1.5,
    intensity_A: float = 140.0,
) -> dict[str, Any]:
    """Compute optimal bid/ask quotes using Cartea-Jaimungal extensions to A-S model.

    Extends Avellaneda-Stoikov (2008) with drift adjustment, inventory penalty skew,
    and adverse selection protection based on order flow imbalance (OFI).

    Mathematical reference: Cartea, A. & Jaimungal, S. (2013), "Modelling asset prices
    for algorithmic and high-frequency trading", Applied Mathematical Finance.

    Parameters
    ----------
    mid_price : float
        Current mid-market price (must be > 0).
    inventory : int
        Current net inventory position.
    order_flow_imbalance : float
        Order flow imbalance in [-1, 1]. +1 = strong buy pressure, -1 = strong sell pressure.
    volatility : float
        Price volatility per unit time (>= 0).
    drift : float
        Expected price drift per unit time. Default 0.0.
    time_to_horizon : float
        Remaining time horizon T (>= 0). Default 1.0.
    risk_aversion : float
        Risk aversion parameter gamma (> 0). Default 0.1.
    inventory_penalty : float
        Additional skew per unit of inventory (>= 0). Default 0.01.
    adverse_selection_aversion : float
        Sensitivity to informed order flow (>= 0). Default 0.5.
    intensity_k : float
        Order arrival intensity rate k (> 0). Default 1.5.
    intensity_A : float
        Baseline order arrival intensity A. Default 140.0.

    Returns
    -------
    dict with keys:
        'bid': float
        'ask': float
        'reservation_price': float — CJ drift-adjusted reservation price
        'adverse_selection_premium': float
        'inventory_aggression': float
        'as_baseline_bid': float — pure A-S bid for comparison
        'as_baseline_ask': float — pure A-S ask for comparison
        'should_pause_quoting': bool
        'fingerprint': str — SHA-256 of canonical JSON of key quote values
    """
    if mid_price <= 0:
        raise ValueError(f"mid_price must be > 0, got {mid_price}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if time_to_horizon < 0:
        raise ValueError(f"time_to_horizon must be >= 0, got {time_to_horizon}")
    if risk_aversion <= 0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")
    if intensity_k <= 0:
        raise ValueError(f"intensity_k must be > 0, got {intensity_k}")

    # 1. Base A-S computations
    r_base = _as_reservation_price(mid_price, inventory, risk_aversion, volatility, time_to_horizon)
    spread = _as_optimal_spread(risk_aversion, volatility, time_to_horizon, intensity_k)

    bid_base = r_base - spread / 2.0
    ask_base = r_base + spread / 2.0

    # 2. CJ drift-adjusted reservation price
    reservation_price = (
        mid_price
        - inventory * risk_aversion * volatility**2 * time_to_horizon
        + drift * time_to_horizon
    )

    # 3. Derived metrics
    adverse_selection_premium = adverse_selection_aversion * abs(order_flow_imbalance) * spread
    inventory_aggression = inventory_penalty * abs(inventory)

    # 4. Final adjusted quotes
    bid = bid_base - inventory_penalty * max(0, inventory) + min(0.0, drift) * time_to_horizon
    ask = ask_base + inventory_penalty * max(0, -inventory) + max(0.0, drift) * time_to_horizon

    # Apply adverse selection adjustments
    bid -= abs(order_flow_imbalance) * adverse_selection_aversion * spread / 2.0
    ask += abs(order_flow_imbalance) * adverse_selection_aversion * spread / 2.0

    # 5. Pause quoting check
    if inventory_penalty > 0:
        should_pause_quoting = abs(inventory) > 5 * (1.0 / inventory_penalty)
    else:
        should_pause_quoting = False

    fp = oprim.sha256_hash(
        oprim.canonical_json(
            {
                "ask": ask,
                "bid": bid,
                "reservation": reservation_price,
                "spread": spread,
            }
        )
    )

    return {
        "bid": bid,
        "ask": ask,
        "reservation_price": reservation_price,
        "adverse_selection_premium": adverse_selection_premium,
        "inventory_aggression": inventory_aggression,
        "as_baseline_bid": bid_base,
        "as_baseline_ask": ask_base,
        "should_pause_quoting": should_pause_quoting,
        "fingerprint": fp,
    }
