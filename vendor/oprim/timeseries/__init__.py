"""Timeseries analysis submodule."""

from oprim.timeseries.autocorrelation import durbin_watson, ljung_box_test
from oprim.timeseries.causality import granger_causality_test
from oprim.timeseries.cointegration import engle_granger_cointegration, johansen_cointegration
from oprim.timeseries.distribution_tests import jarque_bera_test
from oprim.timeseries.equity_curve_segment_label import equity_curve_segment_label
from oprim.timeseries.heteroskedasticity import breusch_pagan_test
from oprim.timeseries.rolling_window_aggregate import rolling_window_aggregate
from oprim.timeseries.stationarity import adf_test, kpss_test
from oprim.timeseries.time_series_split import time_series_split

__all__ = [
    "adf_test",
    "kpss_test",
    "engle_granger_cointegration",
    "johansen_cointegration",
    "ljung_box_test",
    "durbin_watson",
    "granger_causality_test",
    "jarque_bera_test",
    "breusch_pagan_test",
    "time_series_split",
    "equity_curve_segment_label",
    "rolling_window_aggregate",
]
