"""Overview and Market Explorer: computed from transactions on request.

Filtered medians cannot be pre-aggregated (a median of medians is not a
median), and ~240k rows filter in milliseconds, so each request recomputes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services import location as location_service
from app.services.bundle import Bundle
from app.services.common import ALL, InputError, month_label, pct_change, title_case, validate_choice

# The 4-room flat is the most traded type, so ranking towns on it compares
# like with like instead of rewarding towns that happen to sell bigger flats.
REFERENCE_FLAT_TYPE = "4 ROOM"
MIN_SALES_FOR_RANKING = 50
MIN_SALES_FOR_MOVERS = 100
MIN_SALES_FOR_MAP = 10


def meta_payload(bundle: Bundle) -> dict[str, Any]:
    meta = bundle.meta
    quality = meta["quality"]
    txn = bundle.transactions
    flat_models = {
        flat_type: sorted(group["flat_model"].dropna().unique().tolist())
        for flat_type, group in txn.groupby("flat_type")
    }
    eligible = bundle.forecast.groupby("town")["flat_type"].unique()
    forecast_series = {town: sorted(types.tolist()) for town, types in eligible.items()}
    storeys = (
        txn[["storey_range", "storey_mid"]].drop_duplicates().sort_values("storey_mid")["storey_range"].tolist()
    )
    return {
        "towns": bundle.towns,
        "town_labels": {t: title_case(t) for t in bundle.towns},
        "flat_types": bundle.flat_types,
        "common_flat_types": bundle.common_flat_types,
        "flat_type_labels": {t: title_case(t) for t in bundle.flat_types},
        "flat_models": flat_models,
        "storey_ranges": storeys,
        "years": sorted(bundle.complete["year"].unique().astype(int).tolist()),
        "last_complete_month": meta["last_complete_month"],
        "last_complete_label": month_label(bundle.last_month),
        "valuation_month": meta["fair_value"]["valuation_month"],
        "generated_at": meta["generated_at"],
        "quality": {
            k: quality.get(k)
            for k in (
                "total_rows", "valid_rows", "invalid_rows", "valid_pct", "duplicate_rows", "price_outlier_rows",
                "missing_values_total", "earliest_month", "latest_month", "last_complete_month", "checks",
                "checks_passed", "checks_total", "ingested_at", "ingestion_method", "source_last_updated",
                "excluded_from_model_rows", "excluded_from_model_by_reason", "invalid_by_reason",
            )
        },
        "sources": meta["sources"],
        "policy_events": meta["policy_events"],
        "assumptions": meta["affordability_assumptions"],
        "income_benchmark": bundle.income_benchmark,
        "forecast_series": forecast_series,
        "has_town_map": bool(bundle.town_map),
        "has_location": bundle.has_location,
        "location": meta.get("location"),
        "forecast_method": meta["forecast"]["selected_method"],
        "forecast_mape": next(m["mape"] for m in meta["forecast"]["metrics"] if m["method"] == meta["forecast"]["selected_method"]),
        "forecast_origins": len(meta["forecast"]["validation_origins"]),
        "fair_value_model": meta["fair_value"]["selected_model"],
        "fair_value_accuracy": next(
            {k: m[k] for k in ("median_ape", "mape", "within_10pct", "n")}
            for m in meta["fair_value"]["metrics"]
            if m["model"] == meta["fair_value"]["selected_model"]
        ),
    }


def town_map(bundle: Bundle) -> dict[str, Any]:
    """Town shapes for the map picker (static for a given data build)."""
    if not bundle.town_map:
        return {"available": False}
    return {"available": True, **bundle.town_map}


def town_stats(bundle: Bundle, flat_type: str = REFERENCE_FLAT_TYPE) -> dict[str, Any]:
    """One row per town for a flat type: what the map colours and labels."""
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")
    summary = bundle.town_summary
    rows = summary[(summary["flat_type"] == flat_type) & (summary["town"] != ALL)]
    columns = ["town", "median_price_12m", "median_psm_12m", "transactions_12m", "yoy_pct", "change_5y_pct"]
    records = rows[columns].to_dict("records")
    # Too few sales for a trustworthy median: the map greys these out.
    for record in records:
        record["enough_sales"] = record["transactions_12m"] >= MIN_SALES_FOR_MAP
        if not record["enough_sales"]:
            record["median_price_12m"] = None
            record["median_psm_12m"] = None
        place = location_service.town_location(bundle, record["town"], flat_type)
        record["train_minutes"] = place["train_minutes"] if place else None
    return {
        "flat_type": flat_type,
        "towns": records,
        "min_sales": MIN_SALES_FOR_MAP,
        "window_label": f"{month_label(bundle.last_month - pd.DateOffset(months=11))} to {month_label(bundle.last_month)}",
    }


def _window(frame: pd.DataFrame, end: pd.Timestamp, months: int) -> pd.DataFrame:
    start = end - pd.DateOffset(months=months - 1)
    return frame[(frame["month"] >= start) & (frame["month"] <= end)]


def _median(frame: pd.DataFrame, column: str = "resale_price") -> float | None:
    return float(frame[column].median()) if len(frame) else None


def _kpis(frame: pd.DataFrame, end: pd.Timestamp) -> dict[str, Any]:
    recent = _window(frame, end, 3)
    year_ago = _window(frame, end - pd.DateOffset(months=12), 3)
    prior = _window(frame, end - pd.DateOffset(months=3), 3)
    last12 = _window(frame, end, 12)
    prev12 = _window(frame, end - pd.DateOffset(months=12), 12)
    median_now = _median(recent)
    return {
        "median_price": median_now,
        "median_price_year_ago": _median(year_ago),
        "yoy_pct": pct_change(median_now, _median(year_ago)) if len(year_ago) >= 5 and len(recent) >= 5 else None,
        "momentum_pct": pct_change(median_now, _median(prior)) if len(prior) >= 5 and len(recent) >= 5 else None,
        "median_psm": _median(recent, "price_per_sqm"),
        "transactions_3m": int(len(recent)),
        "transactions_12m": int(len(last12)),
        "transactions_12m_change_pct": pct_change(len(last12), len(prev12)) if len(prev12) else None,
        "window_label": f"{month_label(end - pd.DateOffset(months=2))} to {month_label(end)}",
    }


def _monthly_series(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    grouped = frame.groupby("month")["resale_price"]
    monthly = pd.DataFrame(
        {
            "median_price": grouped.median(),
            "p25_price": grouped.quantile(0.25),
            "p75_price": grouped.quantile(0.75),
            "transactions": grouped.size(),
        }
    ).reindex(pd.date_range(start, end, freq="MS"))
    monthly["transactions"] = monthly["transactions"].fillna(0).astype(int)
    # Thin months produce jumpy medians; blank them rather than plot noise.
    thin = monthly["transactions"] < 5
    monthly.loc[thin, ["median_price", "p25_price", "p75_price"]] = np.nan
    monthly.index.name = "month"
    return monthly.reset_index().to_dict("records")


def overview(bundle: Bundle) -> dict[str, Any]:
    txn = bundle.complete
    end = bundle.last_month
    kpis = _kpis(txn, end)

    ytd = txn[(txn["month"].dt.year == end.year) & (txn["month"] <= end)]
    ytd_prev = txn[(txn["month"].dt.year == end.year - 1) & (txn["month"].dt.month <= end.month)]
    kpis["transactions_ytd"] = int(len(ytd))
    kpis["transactions_ytd_change_pct"] = pct_change(len(ytd), len(ytd_prev))
    kpis["ytd_label"] = f"Jan to {end:%b %Y}"

    summary = bundle.town_summary
    reference = summary[(summary["flat_type"] == REFERENCE_FLAT_TYPE) & (summary["town"] != ALL)]
    ranked = reference[reference["transactions_12m"] >= MIN_SALES_FOR_RANKING].sort_values("median_price_12m")
    columns = ["town", "median_price_12m", "median_psm_12m", "transactions_12m", "yoy_pct", "change_5y_pct"]
    movers = reference[reference["transactions_12m"] >= MIN_SALES_FOR_MOVERS].dropna(subset=["yoy_pct"])
    movers = movers.sort_values("yoy_pct", ascending=False)

    national = bundle.market_monthly[(bundle.market_monthly["town"] == ALL) & (bundle.market_monthly["flat_type"] == ALL)]
    trend = national[["month", "median_price", "median_price_3m", "transactions"]].to_dict("records")

    return {
        "kpis": kpis,
        "trend": trend,
        "reference_flat_type": REFERENCE_FLAT_TYPE,
        "most_expensive": ranked.tail(5).iloc[::-1][columns].to_dict("records"),
        "most_affordable": ranked.head(5)[columns].to_dict("records"),
        "rising": movers.head(3)[columns].to_dict("records"),
        "falling": movers.tail(3).iloc[::-1][columns].to_dict("records"),
        "towns_ranked": int(len(ranked)),
        "min_sales_for_ranking": MIN_SALES_FOR_RANKING,
        "min_sales_for_movers": MIN_SALES_FOR_MOVERS,
    }


def market(
    bundle: Bundle,
    town: str = ALL,
    flat_type: str = ALL,
    storey: str = ALL,
    flat_model: str = ALL,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict[str, Any]:
    txn = bundle.complete
    town = validate_choice(town, bundle.towns, "town")
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")
    storey = (storey or ALL).strip().upper()
    flat_model = (flat_model or ALL).strip().upper()
    years = sorted(txn["year"].unique())
    year_from = int(year_from or years[0])
    year_to = int(year_to or years[-1])
    if year_from > year_to:
        raise InputError("year_from must not be after year_to")

    start = pd.Timestamp(year=year_from, month=1, day=1)
    end = min(pd.Timestamp(year=year_to, month=12, day=1), bundle.last_month)

    # Filters other than town (used for the town ranking, which needs every town).
    base = txn[(txn["month"] >= start) & (txn["month"] <= end)]
    if flat_type != ALL:
        base = base[base["flat_type"] == flat_type]
    if storey != ALL:
        base = base[base["storey_range"] == storey]
    if flat_model != ALL:
        base = base[base["flat_model"] == flat_model]
    selected = base if town == ALL else base[base["town"] == town]

    # KPIs look back a year from `end`, beyond the chart's start if needed.
    kpi_frame = txn[txn["month"] <= end]
    for column, value in (("flat_type", flat_type), ("storey_range", storey), ("flat_model", flat_model), ("town", town)):
        if value != ALL:
            kpi_frame = kpi_frame[kpi_frame[column] == value]

    last12 = _window(selected, end, 12)
    distribution = []
    if len(last12):
        prices = last12["resale_price"]
        low, high = prices.quantile(0.01), prices.quantile(0.99)
        step = 25_000 if high - low < 800_000 else 50_000
        edges = np.arange(np.floor(low / step) * step, np.ceil(high / step) * step + step, step)
        counts, edges = np.histogram(prices.clip(edges[0], edges[-1] - 1), bins=edges)
        distribution = [{"from": float(a), "to": float(b), "count": int(c)} for a, b, c in zip(edges[:-1], edges[1:], counts)]

    ranking_frame = _window(base, end, 12)
    ranking_prev = _window(base, end - pd.DateOffset(months=12), 12)
    ranking = (
        ranking_frame.groupby("town")
        .agg(median_psm=("price_per_sqm", "median"), median_price=("resale_price", "median"), transactions=("resale_price", "size"))
        .join(ranking_prev.groupby("town")["resale_price"].median().rename("median_price_prev"))
        .reset_index()
    )
    ranking = ranking[ranking["transactions"] >= 10]
    ranking["yoy_pct"] = [pct_change(a, b) for a, b in zip(ranking["median_price"], ranking["median_price_prev"])]
    ranking = ranking.sort_values("median_psm", ascending=False)

    event = bundle.meta["policy_events"][0] if bundle.meta["policy_events"] else None
    policy = None
    if event:
        pivot = pd.Timestamp(event["month"] + "-01")
        before = kpi_frame[(kpi_frame["month"] >= pivot - pd.DateOffset(months=12)) & (kpi_frame["month"] < pivot)]
        after = kpi_frame[(kpi_frame["month"] >= pivot) & (kpi_frame["month"] < pivot + pd.DateOffset(months=12))]
        earlier = kpi_frame[(kpi_frame["month"] >= pivot - pd.DateOffset(months=24)) & (kpi_frame["month"] < pivot - pd.DateOffset(months=12))]
        if len(before) >= 20 and len(after) >= 20:
            policy = {
                **event,
                "label_month": month_label(pivot),
                "before": {"median_price": _median(before), "transactions": int(len(before)), "growth_pct": pct_change(_median(before), _median(earlier)) if len(earlier) >= 20 else None},
                "after": {"median_price": _median(after), "transactions": int(len(after)), "growth_pct": pct_change(_median(after), _median(before))},
            }

    return {
        "filters": {"town": town, "flat_type": flat_type, "storey": storey, "flat_model": flat_model, "year_from": year_from, "year_to": year_to},
        "kpis": _kpis(kpi_frame, end),
        "series": _monthly_series(selected, start, end),
        "distribution": distribution,
        "distribution_label": f"{month_label(end - pd.DateOffset(months=11))} to {month_label(end)}",
        "town_ranking": ranking[["town", "median_psm", "median_price", "transactions", "yoy_pct"]].to_dict("records"),
        "policy": policy,
        "transactions_in_view": int(len(selected)),
        "end_label": month_label(end),
    }
