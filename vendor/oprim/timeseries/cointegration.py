"""Cointegration tests: Engle-Granger and Johansen.

References
----------
Engle, R.F. & Granger, C.W.J. (1987). Co-integration and Error Correction:
    Representation, Estimation, and Testing. Econometrica, 55(2), 251-276.
Johansen, S. (1991). Estimation and Hypothesis Testing of Cointegration Vectors
    in Gaussian Vector Autoregressive Models. Econometrica, 59(6), 1551-1580.
MacKinnon, J.G. (1991). Critical Values for Cointegration Tests. In R.F. Engle
    and C.W.J. Granger (eds.), Long-Run Economic Relationships: Readings in
    Cointegration. Oxford: Oxford University Press.
Osterwald-Lenum, M. (1992). A Note with Quantiles of the Asymptotic
    Distribution of the Maximum Likelihood Cointegration Rank Test Statistics.
    Oxford Bulletin of Economics and Statistics, 54(3), 461-472.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.timeseries._base import _adf_statistic, _ols_fit

# ---------------------------------------------------------------------------
# Engle-Granger critical values (MacKinnon 1991, Table III, 2-variable case)
# ---------------------------------------------------------------------------
_EG_CV: dict[str, dict[float, float]] = {
    "c": {0.01: -3.9001, 0.05: -3.3377, 0.10: -3.0462},
    "ct": {0.01: -4.3227, 0.05: -3.7809, 0.10: -3.4959},
    "nc": {0.01: -2.5658, 0.05: -1.9393, 0.10: -1.6156},
}

# p-value table for EG (similar to ADF but with EG-specific quantiles)
_EG_PVALUE_TABLE: dict[str, list[tuple[float, float]]] = {
    "c": [
        (-5.0, 0.001),
        (-3.9001, 0.010),
        (-3.6, 0.020),
        (-3.3377, 0.025),
        (-3.1, 0.040),
        (-3.0462, 0.050),
        (-2.8, 0.075),
        (-2.6, 0.100),
        (-2.3, 0.200),
        (-1.9393, 0.500),
        (-1.6156, 0.900),
        (0.0, 0.990),
    ],
    "ct": [
        (-5.5, 0.001),
        (-4.3227, 0.010),
        (-4.1, 0.020),
        (-3.8500, 0.025),
        (-3.7809, 0.050),
        (-3.5900, 0.075),
        (-3.4959, 0.100),
        (-3.2, 0.200),
        (-2.9, 0.500),
        (-2.5, 0.900),
        (-0.8, 0.990),
    ],
    "nc": [
        (-3.5, 0.001),
        (-2.5658, 0.050),
        (-2.3, 0.075),
        (-1.9393, 0.200),
        (-1.6156, 0.500),
        (-1.3, 0.900),
        (0.4, 0.990),
    ],
}


def _eg_pvalue(stat: float, trend: str) -> float:
    """Linear interpolation p-value from EG quantile table."""
    table = _EG_PVALUE_TABLE.get(trend, _EG_PVALUE_TABLE["c"])
    if stat <= table[0][0]:
        return table[0][1]
    if stat >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        s1, p1 = table[i]
        s2, p2 = table[i + 1]
        if s1 <= stat <= s2:
            return float(p1 + (stat - s1) * (p2 - p1) / (s2 - s1))
    return 0.5  # pragma: no cover


def engle_granger_cointegration(
    y: np.ndarray | pd.Series,
    x: np.ndarray | pd.Series,
    *,
    trend: str = "c",
) -> dict:
    """Engle-Granger two-step cointegration test.

    Step 1: OLS regression y = alpha + beta*x + u.
    Step 2: ADF test on residuals (no constant, regression='nc').
    Uses EG-specific critical values (not standard ADF values).

    Parameters
    ----------
    y, x : array-like
        Two time series of equal length.
    trend : {"c", "ct", "nc"}
        Deterministic terms in first-stage OLS regression.

    Returns
    -------
    dict with keys:
        statistic, p_value, critical_values, coef_intercept, coef_slope,
        n_obs, is_cointegrated, regression_type

    Raises
    ------
    ValueError
        If lengths differ or too few observations.

    References
    ----------
    Engle & Granger (1987). Co-integration and Error Correction.
    Econometrica, 55(2), 251-276.
    """
    if isinstance(y, pd.Series):
        y_arr = y.dropna().to_numpy(dtype=float)
    else:
        y_arr = np.asarray(y, dtype=float)
    if isinstance(x, pd.Series):
        x_arr = x.dropna().to_numpy(dtype=float)
    else:
        x_arr = np.asarray(x, dtype=float)

    if len(y_arr) != len(x_arr):
        raise ValueError(f"y and x must have the same length: {len(y_arr)} vs {len(x_arr)}")
    if len(y_arr) < 20:
        raise ValueError(f"Need at least 20 observations, got {len(y_arr)}")
    if trend not in ("c", "ct", "nc"):
        raise ValueError(f"trend must be 'c', 'ct', or 'nc', got {trend!r}")

    n = len(y_arr)

    # Step 1: OLS regression
    if trend == "c":
        X = np.column_stack([np.ones(n), x_arr])
    elif trend == "ct":
        X = np.column_stack([np.ones(n), np.arange(1, n + 1, dtype=float), x_arr])
    else:  # nc
        X = x_arr.reshape(-1, 1)

    coeffs, residuals = _ols_fit(y_arr, X)
    intercept = float(coeffs[0]) if trend != "nc" else 0.0
    slope = float(coeffs[-1])

    # Step 2: ADF on residuals (no constant: standard EG procedure)
    t_stat, _ = _adf_statistic(residuals, lags=0, regression="nc")

    cv = _EG_CV.get(trend, _EG_CV["c"])
    p_value = _eg_pvalue(t_stat, trend)
    is_cointegrated = bool(t_stat < cv[0.05])

    return {
        "statistic": float(t_stat),
        "p_value": float(p_value),
        "critical_values": {
            "1%": cv[0.01],
            "5%": cv[0.05],
            "10%": cv[0.10],
        },
        "coef_intercept": intercept,
        "coef_slope": slope,
        "n_obs": int(n),
        "is_cointegrated": is_cointegrated,
        "regression_type": trend,
    }


# ---------------------------------------------------------------------------
# Johansen (1991) trace test critical values
# Osterwald-Lenum (1992) Table 1 — det_order=0 (const restricted to VECM)
# Format: {n_vars: {r: [90%_cv, 95%_cv, 99%_cv]}}
# ---------------------------------------------------------------------------
_JOHANSEN_TRACE_CV: dict[int, dict[int, list[float]]] = {
    # 1-variable
    1: {0: [7.52, 9.24, 12.97]},
    # 2-variable
    2: {
        0: [17.85, 19.96, 24.60],
        1: [7.52, 9.24, 12.97],
    },
    # 3-variable
    3: {
        0: [31.26, 34.91, 41.07],
        1: [17.85, 19.96, 24.60],
        2: [7.52, 9.24, 12.97],
    },
    # 4-variable
    4: {
        0: [48.28, 53.12, 60.16],
        1: [31.26, 34.91, 41.07],
        2: [17.85, 19.96, 24.60],
        3: [7.52, 9.24, 12.97],
    },
    # 5-variable
    5: {
        0: [70.60, 76.07, 84.45],
        1: [48.28, 53.12, 60.16],
        2: [31.26, 34.91, 41.07],
        3: [17.85, 19.96, 24.60],
        4: [7.52, 9.24, 12.97],
    },
    # 6-variable
    6: {
        0: [90.39, 97.18, 104.20],
        1: [70.60, 76.07, 84.45],
        2: [48.28, 53.12, 60.16],
        3: [31.26, 34.91, 41.07],
        4: [17.85, 19.96, 24.60],
        5: [7.52, 9.24, 12.97],
    },
}

_JOHANSEN_MAXEIG_CV: dict[int, dict[int, list[float]]] = {
    1: {0: [7.52, 9.24, 12.97]},
    2: {
        0: [14.26, 16.87, 21.13],
        1: [7.52, 9.24, 12.97],
    },
    3: {
        0: [21.28, 24.16, 29.51],
        1: [14.26, 16.87, 21.13],
        2: [7.52, 9.24, 12.97],
    },
    4: {
        0: [26.23, 29.51, 36.69],
        1: [21.28, 24.16, 29.51],
        2: [14.26, 16.87, 21.13],
        3: [7.52, 9.24, 12.97],
    },
    5: {
        0: [31.46, 35.07, 41.31],
        1: [26.23, 29.51, 36.69],
        2: [21.28, 24.16, 29.51],
        3: [14.26, 16.87, 21.13],
        4: [7.52, 9.24, 12.97],
    },
    6: {
        0: [36.65, 40.30, 46.82],
        1: [31.46, 35.07, 41.31],
        2: [26.23, 29.51, 36.69],
        3: [21.28, 24.16, 29.51],
        4: [14.26, 16.87, 21.13],
        5: [7.52, 9.24, 12.97],
    },
}


def johansen_cointegration(
    data: np.ndarray | pd.DataFrame,
    *,
    det_order: int = 0,
    k_ar_diff: int = 1,
) -> dict:
    """Johansen cointegration test.

    Tests for the number of cointegrating vectors in a VAR system.

    Parameters
    ----------
    data : array-like, shape (n_obs, n_vars)
        Multivariate time series.
    det_order : int
        Deterministic component: 0 (constant in VECM, most common).
        Currently only det_order=0 is fully supported.
    k_ar_diff : int
        Number of lagged differences in VECM (default 1).

    Returns
    -------
    dict with keys:
        trace_stats, max_eigenvalue_stats, eigenvalues, eigenvectors,
        cointegration_rank, cointegrating_vectors, critical_values_trace,
        critical_values_maxeig, n_obs, n_vars

    Raises
    ------
    ValueError
        If data has fewer than 2 variables or insufficient observations.

    References
    ----------
    Johansen, S. (1991). Estimation and Hypothesis Testing of Cointegration
    Vectors. Econometrica, 59(6), 1551-1580.
    Osterwald-Lenum, M. (1992). Quantiles of the Cointegration Rank Test
    Statistics. Oxford Bulletin of Economics and Statistics, 54(3), 461-472.
    """
    if isinstance(data, pd.DataFrame):
        arr = data.to_numpy(dtype=float)
    else:
        arr = np.asarray(data, dtype=float)

    if arr.ndim != 2:
        raise ValueError("data must be 2-D (n_obs x n_vars)")
    n, k = arr.shape
    if k < 2:
        raise ValueError(f"Need at least 2 variables for Johansen test, got {k}")
    if k > 6:
        raise ValueError(f"Johansen critical values only available for up to 6 variables, got {k}")
    if n < 2 * k + k_ar_diff + 10:
        raise ValueError(f"Insufficient observations for Johansen test: {n}")

    # Step 1: Compute first differences
    dY = np.diff(arr, axis=0)  # (n-1, k)

    # Step 2: Set up lagged differences and levels
    p = k_ar_diff
    # Need obs from index p onwards in dY
    # Effective sample starts at index p (in dY indexing)
    T = n - 1 - p  # effective sample size

    if k >= T:
        raise ValueError(f"Too few effective observations: T={T}, k={k}")

    # Lagged levels: Y_{t-1} at time t (for t=p+1..n-1 in dY indexing: dY[p:])
    Y_lag = arr[p : n - 1]  # shape (T, k)

    # Lagged differences (p lags)
    # dY_lag_i is dY[p-i : n-1-i] for lag i=1..p
    Z2 = None
    if p > 0:
        lag_cols = []
        for i in range(1, p + 1):
            lag_cols.append(dY[p - i : n - 1 - i])  # shape (T, k)
        Z2 = np.hstack(lag_cols)  # shape (T, p*k)

    # Dependent variable: dY[p:]
    Z0 = dY[p:]  # shape (T, k)

    # Step 3: Add deterministic terms and regress out
    if det_order == 0:
        # Constant restricted to VECM (unrestricted constant)
        # Add constant to Z2 (or create if p=0)
        const = np.ones((T, 1))
        if Z2 is not None:
            Z2_aug = np.hstack([Z2, const])
        else:
            Z2_aug = const
    else:
        Z2_aug = Z2 if Z2 is not None else np.ones((T, 1))

    # Regress Z0 and Y_lag on Z2_aug (partial out short-run dynamics)
    def _resid(Y, X):  # pragma: no cover
        """Return residuals of Y regressed on X."""
        coeffs, _ = _ols_fit(Y.T.ravel(), X) if Y.ndim == 1 else _ols_multi(Y, X)  # pragma: no cover
        return Y - X @ coeffs  # pragma: no cover

    def _ols_multi(Y, X):
        """OLS for multivariate Y (n x m) on X (n x k). Returns coefficients (k x m)."""
        coeffs, _, _, _ = np.linalg.lstsq(X, Y, rcond=None)
        return coeffs, Y - X @ coeffs

    # Residuals of Z0 on Z2_aug
    coeffs_0, R0 = _ols_multi(Z0, Z2_aug)  # R0: (T, k)
    # Residuals of Y_lag on Z2_aug
    coeffs_1, R1 = _ols_multi(Y_lag, Z2_aug)  # R1: (T, k)

    # Step 4: Compute moment matrices
    S00 = (R0.T @ R0) / T  # (k, k)
    S01 = (R0.T @ R1) / T  # (k, k)
    S11 = (R1.T @ R1) / T  # (k, k)

    # Step 5: Solve generalized eigenvalue problem
    # S01 @ inv(S11) @ S01.T @ v = lambda * S00 @ v
    # Equivalent: inv(S00) @ S01 @ inv(S11) @ S01.T @ v = lambda * v
    try:
        S11_inv = np.linalg.inv(S11)
        S00_inv = np.linalg.inv(S00)
    except np.linalg.LinAlgError:  # pragma: no cover
        S11_inv = np.linalg.pinv(S11)  # pragma: no cover
        S00_inv = np.linalg.pinv(S00)  # pragma: no cover

    M = S00_inv @ S01 @ S11_inv @ S01.T
    eigenvalues, eigenvectors = np.linalg.eig(M)

    # Keep real parts (should be real in theory)
    eigenvalues = np.real(eigenvalues)
    eigenvectors = np.real(eigenvectors)

    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    # Clip eigenvalues to [0, 1) to avoid log issues
    eigenvalues_clipped = np.clip(eigenvalues, 0.0, 1.0 - 1e-10)

    # Step 6: Trace statistics
    # Trace_r = -T * sum(log(1 - lambda_i), i=r..k-1)
    trace_stats = np.zeros(k)
    for r in range(k):
        trace_stats[r] = float(-T * np.sum(np.log(1.0 - eigenvalues_clipped[r:])))

    # Max eigenvalue statistics
    # MaxEig_r = -T * log(1 - lambda_{r+1})
    maxeig_stats = np.zeros(k)
    for r in range(k):
        maxeig_stats[r] = float(-T * np.log(1.0 - eigenvalues_clipped[r]))

    # Step 7: Determine cointegration rank using trace test at 5%
    # Look up critical values
    cv_trace = _JOHANSEN_TRACE_CV.get(k, {})
    cv_maxeig = _JOHANSEN_MAXEIG_CV.get(k, {})

    cointegration_rank = 0
    for r in range(k):
        cv_95 = cv_trace.get(r, [0, np.inf, np.inf])[1]  # 95% CV
        if trace_stats[r] > cv_95:
            cointegration_rank = r + 1
        else:
            break

    # Cointegrating vectors: eigenvectors corresponding to r largest eigenvalues
    cointegrating_vectors = eigenvectors[:, :cointegration_rank]

    return {
        "trace_stats": trace_stats,
        "max_eigenvalue_stats": maxeig_stats,
        "eigenvalues": eigenvalues,
        "eigenvectors": eigenvectors,
        "cointegration_rank": int(cointegration_rank),
        "cointegrating_vectors": cointegrating_vectors,
        "critical_values_trace": {
            r: {"90%": cvs[0], "95%": cvs[1], "99%": cvs[2]}
            for r, cvs in cv_trace.items()
        },
        "critical_values_maxeig": {
            r: {"90%": cvs[0], "95%": cvs[1], "99%": cvs[2]}
            for r, cvs in cv_maxeig.items()
        },
        "n_obs": int(T),
        "n_vars": int(k),
    }
