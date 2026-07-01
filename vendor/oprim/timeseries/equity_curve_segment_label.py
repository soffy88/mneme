"""A8 — Label equity curve with train/val/oos/gap segments."""

from __future__ import annotations

from datetime import date

import pandas as pd


def equity_curve_segment_label(
    *,
    equity_curve: pd.DataFrame | pd.Series,
    split_dates: dict[str, date],
) -> pd.DataFrame:
    """Assign segment labels to an equity curve based on split dates.

    Uses right-open intervals:
      - train: [start, train_end)
      - gap: [train_end, val_start)
      - val: [val_start, val_end)
      - oos: [oos_start, end]

    Parameters
    ----------
    equity_curve : DataFrame or Series
        Must have a date-like index or a 'date' column, and equity values.
    split_dates : dict
        Must contain keys: train_end, val_start, val_end, oos_start.

    Returns
    -------
    pd.DataFrame with columns [date, equity, segment].

    Raises
    ------
    KeyError
        If required keys are missing from split_dates.
    """
    required_keys = {"train_end", "val_start", "val_end", "oos_start"}
    missing = required_keys - set(split_dates.keys())
    if missing:
        raise KeyError(f"Missing required split_dates keys: {missing}")

    # Normalize to DataFrame with date and equity columns
    if isinstance(equity_curve, pd.Series):
        df = pd.DataFrame({"date": equity_curve.index, "equity": equity_curve.values})
    elif "date" in equity_curve.columns:
        df = equity_curve[["date", "equity"]].copy()
    else:
        df = pd.DataFrame({"date": equity_curve.index, "equity": equity_curve.iloc[:, 0].values})

    # Ensure date column is date type
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)

    train_end = split_dates["train_end"]
    val_start = split_dates["val_start"]
    val_end = split_dates["val_end"]
    oos_start = split_dates["oos_start"]

    def _label(d: date) -> str:
        if d < train_end:
            return "train"
        if d >= train_end and d < val_start:
            return "gap"
        if d >= val_start and d < val_end:
            return "val"
        if d >= oos_start:
            return "oos"
        # Between val_end and oos_start (edge case)
        return "gap"

    df["segment"] = df["date"].apply(_label)
    return df[["date", "equity", "segment"]]
