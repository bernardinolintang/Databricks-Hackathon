"""Find the recent transactions most similar to a flat the user describes."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

OUTPUT_COLUMNS = [
    "month", "town", "flat_type", "block", "street_name", "storey_range", "floor_area_sqm",
    "flat_model", "remaining_lease_years", "resale_price", "price_per_sqm", "similarity",
]


def find_comparables(
    transactions: pd.DataFrame,
    town: str,
    flat_type: str,
    floor_area_sqm: float,
    storey_mid: float,
    remaining_lease_years: float,
    cfg: dict[str, Any],
    flat_model: str | None = None,
) -> pd.DataFrame:
    """Rank recent sales in the same town and flat type by similarity.

    Town and flat type are hard filters. Within them, distance is a weighted
    Euclidean over size, storey, remaining lease and recency, where each
    difference is divided by a scale from the config (e.g. 10 sqm counts the
    same as 8 years of lease). A matching flat model earns a small bonus.
    """
    params = cfg["fair_value"]["comparables"]
    latest = transactions["month"].max()
    cutoff = latest - pd.DateOffset(months=params["lookback_months"] - 1)
    pool = transactions[
        (transactions["town"] == town) & (transactions["flat_type"] == flat_type) & (transactions["month"] >= cutoff)
    ].copy()
    if pool.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    months_ago = (latest.year - pool["month"].dt.year) * 12 + (latest.month - pool["month"].dt.month)
    distance = np.sqrt(
        ((pool["floor_area_sqm"] - floor_area_sqm) / params["scale_floor_area_sqm"]) ** 2
        + ((pool["storey_mid"] - storey_mid) / params["scale_storey"]) ** 2
        + ((pool["remaining_lease_years"] - remaining_lease_years) / params["scale_lease_years"]) ** 2
        + (months_ago / params["scale_recency_months"]) ** 2
    )
    if flat_model:
        distance = distance + np.where(pool["flat_model"] == flat_model, 0.0, 0.25)
    # 100 = identical and sold this month; falls towards 0 as differences grow.
    pool["similarity"] = (100 * np.exp(-distance / 2)).round(0)
    pool["_distance"] = distance
    top = pool.sort_values(["_distance", "month"], ascending=[True, False]).head(params["top_k"])
    return top[OUTPUT_COLUMNS].reset_index(drop=True)
