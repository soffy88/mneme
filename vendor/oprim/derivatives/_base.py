"""Shared Black-Scholes helpers."""


def _d1_d2(S, K, T, r, sigma, q=0.0):
    """Compute d1, d2 for Black-Scholes formula."""
    import numpy as np
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return d1, d2


def _bs_price_from_d1d2(S, K, T, r, sigma, q, d1, d2, option_type):
    """Compute BS price given d1, d2."""
    import numpy as np
    from scipy.stats import norm
    call = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    if option_type == "call":
        return call
    else:  # put
        return call - S * np.exp(-q * T) + K * np.exp(-r * T)  # put-call parity
