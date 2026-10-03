"""Affordability and Fair Value: the two modules that use the buyer's own inputs."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.services import location as location_service
from app.services.bundle import Bundle
from app.services.common import ALL, InputError, month_label, title_case, validate_choice
from flatfair.affordability import LoanAssumptions, assess, max_price, rank_towns
from flatfair.models.comparables import find_comparables
from flatfair.models.fair_value import FEATURE_LABELS, predict_price

MIN_SALES_FOR_TOWN_PRICE = 20
TYPICAL_LOOKBACK_MONTHS = 24


# --------------------------------------------------------------------------- #
# Affordability
# --------------------------------------------------------------------------- #
def _town_prices(bundle: Bundle, flat_type: str) -> pd.DataFrame:
    summary = bundle.town_summary
    rows = summary[(summary["flat_type"] == flat_type) & (summary["town"] != ALL)]
    rows = rows[rows["transactions_12m"] >= MIN_SALES_FOR_TOWN_PRICE]
    return rows.rename(columns={"median_price_12m": "median_price", "transactions_12m": "transactions"})[
        ["town", "median_price", "transactions"]
    ]


def affordability(
    bundle: Bundle,
    monthly_income: float,
    cash_cpf: float,
    flat_type: str,
    town: str,
    price: float | None = None,
    max_repayment: float | None = None,
    interest_rate: float | None = None,
    tenure_years: int | None = None,
    loan_to_value: float | None = None,
) -> dict[str, Any]:
    if not monthly_income or monthly_income <= 0:
        raise InputError("Enter a monthly household income above zero")
    if cash_cpf is None or cash_cpf < 0:
        raise InputError("Cash and CPF savings cannot be negative")
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")
    if flat_type == ALL:
        raise InputError("Choose a flat type")
    town = validate_choice(town, bundle.towns, "town")
    try:
        assumptions = LoanAssumptions.from_config(
            {"affordability": bundle.meta["affordability_assumptions"]},
            annual_interest_rate=interest_rate,
            tenure_years=tenure_years,
            loan_to_value=loan_to_value,
        )
    except ValueError as exc:
        raise InputError(str(exc)) from exc

    prices = _town_prices(bundle, flat_type)
    price_source = "your price"
    if price is None or price <= 0:
        if town == ALL:
            row = bundle.town_summary[(bundle.town_summary["town"] == ALL) & (bundle.town_summary["flat_type"] == flat_type)]
        else:
            row = bundle.town_summary[(bundle.town_summary["town"] == town) & (bundle.town_summary["flat_type"] == flat_type)]
        if row.empty or pd.isna(row.iloc[0]["median_price_12m"]):
            raise InputError(f"No recent {title_case(flat_type)} sales in {title_case(town)}; enter a price instead")
        price = float(row.iloc[0]["median_price_12m"])
        price_source = "the median over the last 12 months"

    result = assess(price, monthly_income, cash_cpf, assumptions)
    budget = max_price(monthly_income, cash_cpf, assumptions, max_repayment)
    ranking = rank_towns(prices, monthly_income, cash_cpf, assumptions, max_repayment)

    benchmark = bundle.income_benchmark
    benchmark_view = None
    if benchmark:
        at_median = assess(price, benchmark["monthly_income"], cash_cpf, assumptions)
        benchmark_view = {
            **benchmark,
            "repayment_ratio": at_median["repayment_ratio"],
            "price_to_income": at_median["price_to_income"],
            "income_vs_benchmark_pct": round((monthly_income / benchmark["monthly_income"] - 1) * 100, 1),
        }

    return {
        "inputs": {
            "monthly_income": monthly_income,
            "cash_cpf": cash_cpf,
            "flat_type": flat_type,
            "town": town,
            "max_repayment": max_repayment,
        },
        "price": price,
        "price_source": price_source,
        "result": result,
        "budget": budget,
        "assumptions": {
            "loan_to_value": assumptions.loan_to_value,
            "annual_interest_rate": assumptions.annual_interest_rate,
            "tenure_years": assumptions.tenure_years,
            "msr_limit": assumptions.msr_limit,
            "comfortable_ratio": assumptions.comfortable_ratio,
        },
        "benchmark": benchmark_view,
        "ranking": ranking.to_dict("records"),
        "within_reach_count": int(ranking["within_reach"].sum()) if not ranking.empty else 0,
        "window_label": f"{month_label(bundle.last_month - pd.DateOffset(months=11))} to {month_label(bundle.last_month)}",
    }


# --------------------------------------------------------------------------- #
# Fair value
# --------------------------------------------------------------------------- #
def _storey_mid(storey_range: str) -> float:
    parts = storey_range.upper().split(" TO ")
    try:
        low, high = int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as exc:
        raise InputError(f"Storey range '{storey_range}' should look like '10 TO 12'") from exc
    return (low + high) / 2


def typical_flat(bundle: Bundle, town: str, flat_type: str, block: str | None = None, street_name: str | None = None) -> dict[str, Any]:
    """The median recent flat of this town and type; used to pre-fill the form
    and as the reference point for 'what moves this estimate'.

    If the buyer names a block, `prefill` holds what is known about that block:
    its lease, and the usual size and model of this flat type there.
    """
    town = validate_choice(town, bundle.towns, "town")
    flat_type = validate_choice(flat_type, bundle.flat_types, "flat type")
    if ALL in (town, flat_type):
        raise InputError("Choose a specific town and flat type")
    txn = bundle.transactions
    recent = txn[(txn["town"] == town) & (txn["flat_type"] == flat_type) & (txn["month"] > bundle.last_month - pd.DateOffset(months=TYPICAL_LOOKBACK_MONTHS))]
    if recent.empty:
        recent = txn[(txn["flat_type"] == flat_type) & (txn["month"] > bundle.last_month - pd.DateOffset(months=TYPICAL_LOOKBACK_MONTHS))]
    if recent.empty:
        raise InputError(f"No recent {title_case(flat_type)} sales to describe")
    storey_mid = recent["storey_mid"].median()
    storey_options = recent[["storey_range", "storey_mid"]].drop_duplicates()
    nearest = storey_options.iloc[(storey_options["storey_mid"] - storey_mid).abs().argsort()].iloc[0]
    models = recent["flat_model"].value_counts()
    named = location_service.find_block(bundle, block, street_name, town)
    prefill = None
    if named is not None:
        sales = txn[(txn["block"] == named["block"]) & (txn["street_name"] == named["street_name"])]
        same_type = sales[sales["flat_type"] == flat_type]
        latest = sales.sort_values("month").iloc[-1]
        # Every flat in a block shares one lease, so the newest sale dates it.
        months_since = (bundle.last_month.year - latest["month"].year) * 12 + bundle.last_month.month - latest["month"].month + 1
        prefill = {
            "block": named["block"],
            "street_name": named["street_name"],
            "label": location_service.address_label(named["block"], named["street_name"]),
            "remaining_lease_years": float(max(1, round(latest["remaining_lease_years"] - months_since / 12))),
            "floor_area_sqm": float(round(same_type["floor_area_sqm"].median())) if len(same_type) else None,
            "flat_model": same_type["flat_model"].value_counts().index[0] if len(same_type) else None,
            "sales_of_type": int(len(same_type)),
        }
    return {
        "town": town,
        "flat_type": flat_type,
        "floor_area_sqm": float(round(recent["floor_area_sqm"].median())),
        "storey_range": nearest["storey_range"],
        "storey_mid": float(nearest["storey_mid"]),
        "remaining_lease_years": float(round(recent["remaining_lease_years"].median())),
        "flat_model": models.index[0],
        "flat_models": models.index.tolist(),
        "floor_area_range": [float(recent["floor_area_sqm"].quantile(0.05)), float(recent["floor_area_sqm"].quantile(0.95))],
        "lease_range": [float(recent["remaining_lease_years"].min()), float(recent["remaining_lease_years"].max())],
        "sales": int(len(recent)),
        "prefill": prefill,
    }


def fair_value(
    bundle: Bundle,
    town: str,
    flat_type: str,
    floor_area_sqm: float,
    storey_range: str,
    remaining_lease_years: float,
    flat_model: str | None = None,
    asking_price: float | None = None,
    block: str | None = None,
    street_name: str | None = None,
) -> dict[str, Any]:
    typical = typical_flat(bundle, town, flat_type)
    town, flat_type = typical["town"], typical["flat_type"]
    named = location_service.find_block(bundle, block, street_name, town)
    if flat_type in ("1 ROOM", "MULTI-GENERATION"):
        raise InputError(f"Too few {title_case(flat_type)} flats are sold to estimate a price")
    if not 20 <= floor_area_sqm <= 300:
        raise InputError("Floor area should be between 20 and 300 sqm")
    if not 1 <= remaining_lease_years <= 99:
        raise InputError("Remaining lease should be between 1 and 99 years")
    if asking_price is not None and asking_price <= 0:
        asking_price = None
    storey_mid = _storey_mid(storey_range)
    flat_model = (flat_model or typical["flat_model"]).upper()

    fv_meta = bundle.meta["fair_value"]
    index_now = fv_meta["market_index_psm_now"]
    months_now = fv_meta["months_since_start_now"]
    flat = {
        "town": town,
        "flat_type": flat_type,
        "flat_model": flat_model,
        "floor_area_sqm": float(floor_area_sqm),
        "storey_mid": storey_mid,
        "remaining_lease_years": float(remaining_lease_years),
    }
    # Location: the named block's own, or the town's typical one if none was named.
    location_inputs = location_service.model_location(bundle)
    typical_place = location_service.typical_location(bundle, town, flat_type)
    typical_place = {f: typical_place.get(f, np.nan) for f in location_inputs}
    place = {f: float(named[f]) for f in location_inputs} if named is not None else typical_place
    flat.update(place)

    # One batch: the flat, the typical flat, and the flat with one attribute
    # swapped to its typical value (to show what each difference is worth).
    swaps = {
        "floor_area_sqm": typical["floor_area_sqm"],
        "storey_mid": typical["storey_mid"],
        "remaining_lease_years": typical["remaining_lease_years"],
        "flat_model": typical["flat_model"],
    }
    typical_row = {**flat, **swaps, **typical_place}
    variants = [flat, typical_row] + [{**flat, feature: value} for feature, value in swaps.items()]
    if named is not None and location_inputs:
        # The same flat in a typical spot in this town: what the location is worth.
        variants.append({**flat, **typical_place})
    predictions = predict_price(bundle.model, pd.DataFrame(variants), index_now, months_now)
    estimate, typical_estimate = float(predictions[0]), float(predictions[1])

    intervals = {row["flat_type"]: row for row in fv_meta["intervals"]}
    band = intervals.get(flat_type, intervals["ALL"])
    low, high = estimate * math.exp(band["lower_log"]), estimate * math.exp(band["upper_log"])

    drivers = []
    descriptions = {
        "floor_area_sqm": lambda v: f"{v:.0f} sqm",
        "storey_mid": lambda v: f"storey {v:.0f}",
        "remaining_lease_years": lambda v: f"{v:.0f} years left",
        "flat_model": lambda v: title_case(str(v)) if str(v).isupper() else str(v),
    }
    for (feature, typical_value), swapped_price in zip(swaps.items(), predictions[2 : 2 + len(swaps)]):
        yours = flat[feature]
        if yours == typical_value:
            continue
        drivers.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS[feature],
                "yours": descriptions[feature](yours),
                "typical": descriptions[feature](typical_value),
                "effect": round(estimate - float(swapped_price), -2),
            }
        )
    if named is not None and location_inputs:
        drivers.append(
            {
                "feature": "location",
                "label": "Location",
                "yours": "This block",
                "typical": f"a typical spot in {title_case(town)}",
                "effect": round(estimate - float(predictions[-1]), -2),
            }
        )
    drivers.sort(key=lambda d: abs(d["effect"]), reverse=True)

    comparison = None
    if asking_price:
        difference = asking_price - estimate
        position = "below" if asking_price < low else "above" if asking_price > high else "within"
        labels = {
            "below": "Below the usual range",
            "within": "Within the usual range",
            "above": "Above the usual range",
        }
        comparison = {
            "asking_price": asking_price,
            "difference": round(difference, -2),
            "difference_pct": round(difference / estimate * 100, 1),
            "position": position,
            "label": labels[position],
        }

    comps = find_comparables(
        bundle.transactions, town, flat_type, floor_area_sqm, storey_mid, remaining_lease_years,
        {"fair_value": {"comparables": bundle.meta["comparables"]}}, flat_model=flat_model,
        origin=(float(named["latitude"]), float(named["longitude"])) if named is not None else None,
    )
    comparables = comps.to_dict("records")
    for row in comparables:
        if "train_m" in row:
            row["train_minutes"] = location_service.minutes(bundle, row.pop("train_m"))
    metrics = {m["model"]: m for m in fv_meta["metrics"]}
    selected = metrics[fv_meta["selected_model"]]
    baseline = metrics[fv_meta["baseline_model"]]
    return {
        "flat": {**{k: v for k, v in flat.items() if k not in location_inputs}, "storey_range": storey_range.upper()},
        "location": location_service.nearby(bundle, named) if named is not None else None,
        "location_in_model": bool(location_inputs),
        "has_location": bundle.has_location,
        "estimate": round(estimate, -3),
        "range": [round(low, -3), round(high, -3)],
        "interval_level": fv_meta["interval_level"],
        "interval_basis": band["flat_type"],
        "comparison": comparison,
        "typical": {**typical, "estimate": round(typical_estimate, -3)},
        "drivers": drivers,
        "importance": fv_meta["importance"],
        "comparables": comparables,
        "valuation_month": month_label(pd.Timestamp(fv_meta["valuation_month"] + "-01")),
        "accuracy": {
            "model": fv_meta["selected_model"],
            "holdout_period": fv_meta["holdout_period"],
            "holdout_rows": fv_meta["holdout_rows"],
            "median_ape": selected["median_ape"],
            "mape": selected["mape"],
            "within_10pct": selected["within_10pct"],
            "baseline_mape": baseline["mape"],
            "mae": selected["mae"],
            "baseline_mae": baseline["mae"],
            # The same model without location, where the build measured it.
            "flat_only_median_ape": metrics.get("gradient_boosting_flat_only", {}).get("median_ape"),
        },
    }

