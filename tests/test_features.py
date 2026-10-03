import pandas as pd
import pytest

from flatfair.features.market import ALL, build_market_index, build_market_monthly, build_town_summary


def test_market_monthly_has_rollups_and_full_grid(cfg, synthetic_transactions):
    monthly = build_market_monthly(synthetic_transactions, cfg)
    keys = set(zip(monthly["town"], monthly["flat_type"]))
    assert (ALL, ALL) in keys and ("TAMPINES", ALL) in keys and (ALL, "4 ROOM") in keys
    # Every series covers every month, so lags line up.
    assert monthly.groupby(["town", "flat_type"]).size().eq(48).all()


def test_market_monthly_median_matches_raw(cfg, synthetic_transactions):
    monthly = build_market_monthly(synthetic_transactions, cfg)
    month = pd.Timestamp("2022-06-01")
    raw = synthetic_transactions[
        (synthetic_transactions["town"] == "TAMPINES")
        & (synthetic_transactions["flat_type"] == "4 ROOM")
        & (synthetic_transactions["month"] == month)
    ]["resale_price"]
    row = monthly[(monthly["town"] == "TAMPINES") & (monthly["flat_type"] == "4 ROOM") & (monthly["month"] == month)].iloc[0]
    assert row["median_price"] == pytest.approx(raw.median())
    assert row["transactions"] == len(raw)


def test_yoy_uses_twelve_month_lag(cfg, synthetic_transactions):
    monthly = build_market_monthly(synthetic_transactions, cfg)
    series = monthly[(monthly["town"] == ALL) & (monthly["flat_type"] == ALL)].set_index("month")
    month = pd.Timestamp("2023-03-01")
    expected = (series.loc[month, "median_price"] / series.loc[month - pd.DateOffset(months=12), "median_price"] - 1) * 100
    assert series.loc[month, "yoy_pct"] == pytest.approx(expected, abs=0.01)


def test_market_index_uses_only_past_months(cfg, synthetic_transactions):
    index = build_market_index(synthetic_transactions, cfg).set_index("month")
    month = pd.Timestamp("2022-06-01")
    window = synthetic_transactions[
        (synthetic_transactions["month"] >= month - pd.DateOffset(months=3))
        & (synthetic_transactions["month"] < month)
    ]
    assert index.loc[month, "market_index_psm"] == pytest.approx(window["price_per_sqm"].median(), abs=0.01)
    # One month beyond the data, so "today" has an index.
    assert index.index.max() == synthetic_transactions["month"].max() + pd.DateOffset(months=1)


def test_town_summary_windows(cfg, synthetic_transactions):
    summary = build_town_summary(synthetic_transactions, cfg)
    row = summary[(summary["town"] == "QUEENSTOWN") & (summary["flat_type"] == "4 ROOM")].iloc[0]
    assert row["transactions_12m"] == 12 * 12
    assert row["median_price_12m"] > 0
    assert pd.notna(row["yoy_pct"])
