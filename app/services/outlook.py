"""Forecast and Compare."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.bundle import Bundle
from app.services.common import ALL, InputError, month_label, pct_change, title_case, validate_choice
from flatfair.affordability import LoanAssumptions, assess
from flatfair.models.interpret import interpret_forecast

HISTORY_MONTHS = 48
METHOD_LABELS = {
    "naive_last": "Last month's price",
    "rolling_3m": "Average of the last 3 months",
    "linear_trend": "Straight-line trend (24 months)",
    "gbm": "Machine learning model",
}
MAX_COMPARE = 3


def _place(town: str, flat_type: str) -> str:
    """Short label, e.g. 'Tampines 4-room flats'."""
    town_part = "Singapore" if town == ALL else title_case(town)
    return f"{town_part} flats" if flat_type == ALL else f"{town_part} {title_case(flat_type)} flats"


def _subject(town: str, flat_type: str) -> str:
    """Sentence subject, e.g. '4-room prices in Tampines'."""
    where = "Singapore" if town == ALL else title_case(town)
    what = "Resale prices" if flat_type == ALL else f"{title_case(flat_type)} prices"
    return f"{what} in {where}"


def forecast(bundle: Bundle, town: str, flat_type: str) -> dict[str, Any]:
    town = validate_choice(town, bundle.towns, "town")
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")
    meta = bundle.meta["forecast"]
    rows = bundle.forecast[(bundle.forecast["town"] == town) & (bundle.forecast["flat_type"] == flat_type)].sort_values("horizon")

    methods = [
        {**m, "label": METHOD_LABELS.get(m["method"], m["method"])}
        for m in sorted(meta["metrics"], key=lambda m: m["mape"])
    ]
    evaluation = {
        "methods": methods,
        "selected_method": meta["selected_method"],
        "selected_label": METHOD_LABELS.get(meta["selected_method"], meta["selected_method"]),
        "validation_period": meta["validation_period"],
        "validation_origins": meta["validation_origins"],
        "backtest_rows": meta["backtest_rows"],
        "series_count": meta["series_count"],
        "interval_level": meta["interval_level"],
        "mlflow_run_id": meta.get("mlflow_run_id"),
    }

    if rows.empty:
        alternatives = bundle.forecast[bundle.forecast["town"] == town]["flat_type"].unique().tolist()
        return {
            "available": False,
            "town": town,
            "flat_type": flat_type,
            "reason": (
                f"There are too few sales of {_place(town, flat_type)} to forecast. "
                "We need three years of history and at least 60 sales in the last 12 months."
            ),
            "alternatives": sorted(alternatives),
            "evaluation": evaluation,
        }

    history = bundle.market_monthly[(bundle.market_monthly["town"] == town) & (bundle.market_monthly["flat_type"] == flat_type)]
    history = history[history["month"] > bundle.last_month - pd.DateOffset(months=HISTORY_MONTHS)]
    history = history[["month", "median_price", "median_price_3m", "transactions"]].copy()
    history.loc[history["transactions"] < 5, "median_price"] = None

    final = rows.iloc[-1]
    reading = interpret_forecast(
        _subject(town, flat_type),
        float(final["recent_level_price"]),
        float(final["forecast_price"]),
        float(final["lower_price"]),
        float(final["upper_price"]),
        month_label(final["month"]),
        meta["interval_level"],
    )
    return {
        "available": True,
        "town": town,
        "flat_type": flat_type,
        "place": _place(town, flat_type),
        "history": history.to_dict("records"),
        "forecast": rows[["month", "horizon", "forecast_price", "lower_price", "upper_price"]].to_dict("records"),
        "recent_level": float(final["recent_level_price"]),
        "last_actual_month": month_label(bundle.last_month),
        "volume_tier": final["volume_tier"],
        "reading": reading,
        "evaluation": evaluation,
    }


def compare(bundle: Bundle, towns: list[str], flat_type: str, monthly_income: float | None, cash_cpf: float | None) -> dict[str, Any]:
    if not towns:
        raise InputError("Choose at least one town to compare")
    if len(towns) > MAX_COMPARE:
        raise InputError(f"Compare up to {MAX_COMPARE} towns at a time")
    towns = [validate_choice(t, bundle.towns, "town") for t in towns]
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")

    benchmark = bundle.income_benchmark
    income_source = "yours"
    if not monthly_income:
        if benchmark is None:
            monthly_income = None
        else:
            monthly_income, income_source = benchmark["monthly_income"], "median"
    assumptions = LoanAssumptions.from_config({"affordability": bundle.meta["affordability_assumptions"]})

    summary = bundle.town_summary
    cards = []
    series = []
    start = bundle.last_month - pd.DateOffset(months=59)
    for town in towns:
        row = summary[(summary["town"] == town) & (summary["flat_type"] == flat_type)]
        if row.empty or pd.isna(row.iloc[0]["median_price_12m"]):
            cards.append({"town": town, "available": False})
            continue
        row = row.iloc[0]
        fc = bundle.forecast[(bundle.forecast["town"] == town) & (bundle.forecast["flat_type"] == flat_type)].sort_values("horizon")
        outlook = None
        if not fc.empty:
            last = fc.iloc[-1]
            outlook = {
                "month": month_label(last["month"]),
                "forecast_price": float(last["forecast_price"]),
                "lower_price": float(last["lower_price"]),
                "upper_price": float(last["upper_price"]),
                "change_pct": pct_change(float(last["forecast_price"]), float(last["recent_level_price"])),
            }
        afford = None
        if monthly_income:
            # Default savings: exactly the minimum upfront cost, so the ratio reflects the loan.
            result = assess(float(row["median_price_12m"]), monthly_income, cash_cpf if cash_cpf is not None else 0.0, assumptions)
            afford = {k: result[k] for k in ("monthly_repayment", "repayment_ratio", "price_to_income", "status", "status_label", "upfront_needed")}
        cards.append(
            {
                "town": town,
                "available": True,
                "median_price": float(row["median_price_12m"]),
                "median_psm": float(row["median_psm_12m"]),
                "transactions_12m": int(row["transactions_12m"]),
                "yoy_pct": row["yoy_pct"],
                "change_5y_pct": row["change_5y_pct"],
                "momentum_pct": row["momentum_pct"],
                "outlook": outlook,
                "affordability": afford,
            }
        )
        history = bundle.market_monthly[
            (bundle.market_monthly["town"] == town)
            & (bundle.market_monthly["flat_type"] == flat_type)
            & (bundle.market_monthly["month"] >= start)
        ]
        series.append({"town": town, "points": history[["month", "median_price_3m", "transactions_3m"]].to_dict("records")})

    available = [c for c in cards if c["available"]]
    verdicts = []
    if len(available) >= 2:
        cheapest = min(available, key=lambda c: c["median_price"])
        dearest = max(available, key=lambda c: c["median_price"])
        gap = dearest["median_price"] - cheapest["median_price"]
        verdicts.append(
            f"{title_case(cheapest['town'])} is the cheapest at ${cheapest['median_price']:,.0f}, "
            f"${gap:,.0f} less than {title_case(dearest['town'])}."
        )
        with_5y = [c for c in available if c["change_5y_pct"] is not None and not pd.isna(c["change_5y_pct"])]
        if len(with_5y) >= 2:
            fastest = max(with_5y, key=lambda c: c["change_5y_pct"])
            verdicts.append(f"{title_case(fastest['town'])} went up the most in five years ({fastest['change_5y_pct']:+.1f}%).")
        if all(c["affordability"] for c in available):
            best = min(available, key=lambda c: c["affordability"]["repayment_ratio"])
            who = "your income" if income_source == "yours" else "the median household income"
            verdicts.append(
                f"On {who}, {title_case(best['town'])} is the easiest to repay "
                f"({best['affordability']['repayment_ratio']:.0%} of monthly income)."
            )
    return {
        "flat_type": flat_type,
        "cards": cards,
        "series": series,
        "verdicts": [v.replace("  ", " ") for v in verdicts],
        "monthly_income": monthly_income,
        "income_source": income_source,
        "window_label": f"{month_label(bundle.last_month - pd.DateOffset(months=11))} to {month_label(bundle.last_month)}",
    }
