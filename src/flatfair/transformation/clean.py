"""Bronze -> silver: typed, standardised, and flagged. Nothing is deleted.

Every bronze row survives into silver. Problems are recorded as flags so that
each consumer (market stats, model training) can state exactly what it excludes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from flatfair.transformation.parsers import (
    parse_month,
    parse_remaining_lease,
    parse_storey_range,
    standardise_flat_type,
    standardise_text,
)

BASE_MONTH = pd.Timestamp("2017-01-01")

SOURCE_COLUMNS = [
    "month",
    "town",
    "flat_type",
    "block",
    "street_name",
    "storey_range",
    "floor_area_sqm",
    "flat_model",
    "lease_commence_date",
    "remaining_lease",
    "resale_price",
]


def months_since_start(month: pd.Series) -> pd.Series:
    return (month.dt.year - BASE_MONTH.year) * 12 + (month.dt.month - BASE_MONTH.month)


def _map_unique(series: pd.Series, func) -> pd.Series:
    """Apply a scalar parser once per distinct value; the fields are low-cardinality."""
    lookup = {value: func(value) for value in series.dropna().unique()}
    return series.map(lookup)


def _robust_z(values: pd.Series) -> pd.Series:
    median = values.median()
    mad = (values - median).abs().median()
    if not np.isfinite(mad) or mad == 0:
        return pd.Series(0.0, index=values.index)
    # 0.6745 rescales MAD so the score is comparable to a standard z-score.
    return 0.6745 * (values - median) / mad


def build_silver(bronze: pd.DataFrame, cfg: dict[str, Any], as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Clean the bronze snapshot.

    `as_of` is the date the data was pulled; transactions dated after it are
    flagged as future-dated. Defaults to the bronze ingestion timestamp.
    """
    missing = [c for c in SOURCE_COLUMNS if c not in bronze.columns]
    if missing:
        raise ValueError(f"Bronze table is missing required columns: {missing}")
    q = cfg["quality"]

    if as_of is None:
        stamps = pd.to_datetime(bronze.get("_ingested_at"), errors="coerce", utc=True) if "_ingested_at" in bronze else None
        as_of = stamps.max().tz_localize(None) if stamps is not None and stamps.notna().any() else pd.Timestamp.now()
    as_of_month = pd.Timestamp(as_of).to_period("M").to_timestamp()

    silver = pd.DataFrame(index=bronze.index)
    silver["source_row"] = np.arange(len(bronze))
    silver["month"] = parse_month(bronze["month"])
    silver["year"] = silver["month"].dt.year.astype("Int64")
    silver["quarter"] = silver["month"].dt.quarter.astype("Int64")
    silver["months_since_start"] = months_since_start(silver["month"]).astype("Int64")

    silver["town"] = standardise_text(bronze["town"])
    silver["flat_type"] = standardise_flat_type(bronze["flat_type"])
    silver["flat_model"] = standardise_text(bronze["flat_model"])
    silver["block"] = standardise_text(bronze["block"])
    silver["street_name"] = standardise_text(bronze["street_name"])
    silver["storey_range"] = standardise_text(bronze["storey_range"])

    storey = _map_unique(silver["storey_range"], parse_storey_range)
    silver["storey_low"] = storey.str[0].astype(float)
    silver["storey_high"] = storey.str[1].astype(float)
    silver["storey_mid"] = storey.str[2].astype(float)

    silver["floor_area_sqm"] = pd.to_numeric(bronze["floor_area_sqm"], errors="coerce")
    silver["resale_price"] = pd.to_numeric(bronze["resale_price"], errors="coerce")
    silver["lease_commence_year"] = pd.to_numeric(bronze["lease_commence_date"], errors="coerce")

    # Lease: prefer the reported value; derive it from the commencement year when
    # the text is unreadable so one bad string does not cost us the row.
    txn_year_fraction = silver["month"].dt.year + (silver["month"].dt.month - 1) / 12.0
    reported = _map_unique(bronze["remaining_lease"].astype("string"), parse_remaining_lease).astype(float)
    derived = q["lease_term_years"] - (txn_year_fraction - silver["lease_commence_year"])
    silver["remaining_lease_years"] = reported.where(reported.notna(), derived).round(2)
    silver["remaining_lease_source"] = np.where(reported.notna(), "reported", np.where(derived.notna(), "derived", "missing"))
    silver["lease_age_years"] = (txn_year_fraction - silver["lease_commence_year"]).round(2)
    silver["price_per_sqm"] = (silver["resale_price"] / silver["floor_area_sqm"]).where(silver["floor_area_sqm"] > 0).round(2)

    # --- validity checks: each produces a named reason -------------------------
    checks = {
        "unparseable_month": silver["month"].isna(),
        "future_month": silver["month"] > as_of_month,
        "missing_town": silver["town"].isna(),
        "missing_flat_type": silver["flat_type"].isna(),
        "non_positive_price": ~(silver["resale_price"] > 0),
        "non_positive_floor_area": ~(silver["floor_area_sqm"] > 0),
        "implausible_floor_area": (silver["floor_area_sqm"] > 0)
        & ~silver["floor_area_sqm"].between(q["min_floor_area_sqm"], q["max_floor_area_sqm"]),
        "unparseable_storey_range": silver["storey_mid"].isna(),
        "impossible_lease": ~silver["remaining_lease_years"].between(0, q["lease_term_years"], inclusive="right")
        | ~silver["lease_commence_year"].between(q["min_lease_commence_year"], silver["month"].dt.year),
    }
    reasons = pd.Series("", index=silver.index)
    for name, mask in checks.items():
        mask = mask.fillna(True) if name != "future_month" else mask.fillna(False)
        reasons = reasons.where(~mask, reasons + name + ";")
    silver["invalid_reasons"] = reasons.str.rstrip(";")
    silver["is_valid"] = silver["invalid_reasons"] == ""

    # --- warnings: kept as valid, but visible ----------------------------------
    silver["lease_mismatch"] = (
        reported.notna() & derived.notna() & ((reported - derived).abs() > q["lease_mismatch_tolerance_years"])
    )

    # The source has no transaction id, so identical rows cannot be told apart
    # from two genuinely identical sales (same block, storey band, size, price,
    # month). We flag them and keep them; see docs/methodology.md.
    silver["is_duplicate"] = bronze[SOURCE_COLUMNS].duplicated(keep="first").to_numpy()

    silver["is_price_outlier"] = False
    valid = silver[silver["is_valid"]]
    if not valid.empty:
        log_psm = np.log(valid["price_per_sqm"])
        groups = [valid["town"], valid["flat_type"], valid["year"]]
        z = log_psm.groupby(groups, observed=True).transform(_robust_z)
        group_size = log_psm.groupby(groups, observed=True).transform("size")
        outlier_idx = z.index[(z.abs() > q["outlier_robust_z"]) & (group_size >= q["outlier_min_group_size"])]
        silver.loc[outlier_idx, "is_price_outlier"] = True

    # Price outliers are flagged but NOT excluded from modelling. Inspecting them
    # shows legitimate sales explained by features the model sees (premium DBSS
    # blocks at the top, short-lease flats at the bottom), so dropping them
    # would bias the model against exactly those flats.
    excluded_types = set(cfg["fair_value"]["excluded_flat_types"])
    exclusion = np.select(
        [~silver["is_valid"], silver["flat_type"].isin(excluded_types)],
        ["invalid_record", "sparse_flat_type"],
        default="",
    )
    silver["model_exclusion_reason"] = exclusion
    silver["exclude_from_model"] = exclusion != ""
    # Carried forward so downstream steps know which month was still open.
    silver["pulled_at"] = pd.Timestamp(as_of)

    for column in ["town", "flat_type", "flat_model", "block", "street_name", "storey_range"]:
        silver[column] = silver[column].astype(object).where(silver[column].notna(), None)
    return silver.reset_index(drop=True)
