"""Silver -> gold market aggregates.

Medians are used for headline comparisons because a handful of million-dollar
transactions can pull a town's mean a long way.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ALL = "ALL"


def analysis_transactions(silver: pd.DataFrame, last_month: pd.Timestamp) -> pd.DataFrame:
    """Valid transactions up to the last complete month. Duplicates and price
    outliers are kept: medians are robust to them and they are real records."""
    mask = silver["is_valid"] & (silver["month"] <= last_month)
    return silver.loc[mask].copy()


def _aggregate(txn: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    grouped = txn.groupby(keys, observed=True)
    out = grouped.agg(
        transactions=("resale_price", "size"),
        median_price=("resale_price", "median"),
        mean_price=("resale_price", "mean"),
        median_psm=("price_per_sqm", "median"),
        median_floor_area=("floor_area_sqm", "median"),
    )
    quartiles = grouped["resale_price"].quantile([0.25, 0.75]).unstack()
    out["p25_price"], out["p75_price"] = quartiles[0.25], quartiles[0.75]
    out = out.reset_index()
    for column in ("town", "flat_type"):
        if column not in out.columns:
            out[column] = ALL
    return out


def _trailing_pooled_median(txn: pd.DataFrame, keys: list[str], window: int) -> pd.DataFrame:
    """Median over all transactions in the trailing `window` months, per month.

    Pooling transactions is steadier than averaging monthly medians when a
    town x flat type has only a few sales in a month.
    """
    frames = []
    for shift in range(window):
        shifted = txn[keys + ["month", "resale_price"]].copy()
        shifted["month"] = shifted["month"] + pd.DateOffset(months=shift)
        frames.append(shifted)
    pooled = pd.concat(frames, ignore_index=True)
    out = pooled.groupby(keys + ["month"], observed=True)["resale_price"].agg(["median", "size"]).reset_index()
    return out.rename(columns={"median": f"median_price_{window}m", "size": f"transactions_{window}m"})


def build_market_monthly(txn: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Monthly market stats per town x flat type, with ALL rollups on both axes.

    Each series is laid on the full month grid (months without sales have
    transactions = 0 and empty prices) so lags and year-on-year line up.
    """
    market = cfg["market"]
    window = market["kpi_window_months"]
    first, last = txn["month"].min(), txn["month"].max()
    grid = pd.date_range(first, last, freq="MS")

    parts = []
    for keys in (["town", "flat_type"], ["town"], ["flat_type"], []):
        monthly = _aggregate(txn, ["month"] + keys)
        pooled = _trailing_pooled_median(txn, keys, window)
        for column in ("town", "flat_type"):
            if column not in pooled.columns:
                pooled[column] = ALL
        monthly = monthly.merge(pooled, on=["month", "town", "flat_type"], how="outer")
        parts.append(monthly)
    combined = pd.concat(parts, ignore_index=True)
    combined = combined[combined["month"] <= last]

    series_frames = []
    for (town, flat_type), series in combined.groupby(["town", "flat_type"], observed=True):
        series = series.set_index("month").reindex(grid)
        series.index.name = "month"
        series["town"], series["flat_type"] = town, flat_type
        series["transactions"] = series["transactions"].fillna(0).astype(int)
        series[f"transactions_{window}m"] = series[f"transactions_{window}m"].fillna(0).astype(int)
        series["mom_pct"] = series["median_price"].pct_change(fill_method=None) * 100
        series["yoy_pct"] = (series["median_price"] / series["median_price"].shift(12) - 1) * 100
        smooth = series[f"median_price_{window}m"]
        series[f"yoy_pct_{window}m"] = (smooth / smooth.shift(12) - 1) * 100
        for w in market["rolling_windows"]:
            series[f"rolling_avg_{w}m"] = series["median_price"].rolling(w, min_periods=max(2, w // 2)).mean()
        series_frames.append(series.reset_index())
    out = pd.concat(series_frames, ignore_index=True)

    numeric = out.select_dtypes(include=[np.floating]).columns
    out[numeric] = out[numeric].round(2)
    return out.sort_values(["town", "flat_type", "month"]).reset_index(drop=True)


def _window_stats(txn: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, keys: list[str], suffix: str) -> pd.DataFrame:
    window = txn[(txn["month"] >= start) & (txn["month"] <= end)]
    out = window.groupby(keys, observed=True).agg(
        **{
            f"median_price_{suffix}": ("resale_price", "median"),
            f"median_psm_{suffix}": ("price_per_sqm", "median"),
            f"transactions_{suffix}": ("resale_price", "size"),
        }
    )
    return out.reset_index()


def build_town_summary(txn: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per town x flat type (plus ALL rollups) describing the current market.

    Windows of pooled transactions are compared with the same windows earlier:
      yoy_pct       latest 12 months vs the 12 months before
      momentum_pct  latest 3 months vs the 3 months before
      change_5y_pct latest 12 months vs the 12 months ending five years ago
    """
    market = cfg["market"]
    last = txn["month"].max()
    n = market["summary_window_months"]
    k = market["kpi_window_months"]

    def back(months: int) -> pd.Timestamp:
        return last - pd.DateOffset(months=months)

    windows = {
        "12m": (back(n - 1), last),
        "prev12m": (back(2 * n - 1), back(n)),
        "5y_ago": (back(60 + n - 1), back(60)),
        "3m": (back(k - 1), last),
        "prev3m": (back(2 * k - 1), back(k)),
        "3m_year_ago": (back(12 + k - 1), back(12)),
    }

    parts = []
    for keys in (["town", "flat_type"], ["town"], ["flat_type"], []):
        frame = None
        scoped = txn.assign(_all=1)
        group_keys = keys or ["_all"]
        for suffix, (start, end) in windows.items():
            stats = _window_stats(scoped, start, end, group_keys, suffix)
            frame = stats if frame is None else frame.merge(stats, on=group_keys, how="outer")
        for column in ("town", "flat_type"):
            if column not in frame.columns:
                frame[column] = ALL
        parts.append(frame.drop(columns=[c for c in ["_all"] if c in frame.columns]))
    summary = pd.concat(parts, ignore_index=True)

    minimum = market["min_transactions_for_stat"]

    def pct(numerator: str, denominator: str) -> pd.Series:
        enough = (summary[f"transactions_{numerator}"] >= minimum) & (summary[f"transactions_{denominator}"] >= minimum)
        change = (summary[f"median_price_{numerator}"] / summary[f"median_price_{denominator}"] - 1) * 100
        return change.where(enough).round(2)

    summary["yoy_pct"] = pct("12m", "prev12m")
    summary["change_5y_pct"] = pct("12m", "5y_ago")
    summary["momentum_pct"] = pct("3m", "prev3m")
    summary["yoy_pct_3m"] = pct("3m", "3m_year_ago")
    for column in summary.columns:
        if column.startswith("transactions_"):
            summary[column] = summary[column].fillna(0).astype(int)
    summary["as_of_month"] = last
    keep = [
        "town", "flat_type", "as_of_month",
        "median_price_12m", "median_psm_12m", "transactions_12m",
        "median_price_3m", "median_psm_3m", "transactions_3m",
        "median_price_prev12m", "median_price_5y_ago",
        "yoy_pct", "yoy_pct_3m", "momentum_pct", "change_5y_pct",
    ]
    return summary[keep].sort_values(["flat_type", "town"]).reset_index(drop=True)


def build_market_index(txn: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """National price level per month, built only from *earlier* months.

    index(m) = median price per sqm over the `index_window_months` months before
    m. Using past months only means the fair value model can be scored on a
    future month without seeing that month's prices, and gives a value for the
    month after the data ends ("today").
    """
    window = cfg["fair_value"]["index_window_months"]
    first, last = txn["month"].min(), txn["month"].max()
    rows = []
    for month in pd.date_range(first, last + pd.DateOffset(months=1), freq="MS"):
        start, end = month - pd.DateOffset(months=window), month - pd.DateOffset(months=1)
        psm = txn.loc[(txn["month"] >= start) & (txn["month"] <= end), "price_per_sqm"]
        rows.append({"month": month, "market_index_psm": psm.median() if len(psm) else np.nan, "index_transactions": len(psm)})
    index = pd.DataFrame(rows)
    # January 2017 has no earlier month; reuse the first available level.
    index["market_index_psm"] = index["market_index_psm"].bfill().round(2)
    return index
