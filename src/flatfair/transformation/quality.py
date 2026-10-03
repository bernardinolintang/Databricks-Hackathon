"""Data quality summary shown in the app's Data Health indicator."""

from __future__ import annotations

from typing import Any

import pandas as pd

from flatfair.transformation.clean import SOURCE_COLUMNS


def last_complete_month(silver: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.Timestamp:
    """Latest month that had fully ended when the data was pulled.

    Records are published by registration date, so the month containing the pull
    date is still filling up. Analytics stop at the month before it.
    """
    if as_of is None:
        as_of = pd.to_datetime(silver["pulled_at"]).max()
    pull_month = pd.Timestamp(as_of).to_period("M").to_timestamp()
    months = silver.loc[silver["is_valid"], "month"]
    complete = months[months < pull_month]
    if complete.empty:
        raise ValueError("No complete month of valid transactions found")
    return complete.max()


def build_quality_summary(
    bronze: pd.DataFrame,
    silver: pd.DataFrame,
    cfg: dict[str, Any],
    ingestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ingestion = ingestion or {}
    total = len(silver)
    valid = int(silver["is_valid"].sum())

    reason_counts: dict[str, int] = {}
    for reasons in silver.loc[~silver["is_valid"], "invalid_reasons"]:
        for reason in reasons.split(";"):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # Missing = empty or absent in the raw source, before any derivation.
    raw = bronze[[c for c in SOURCE_COLUMNS if c in bronze.columns]].astype("string")
    missing_by_column = {c: int((raw[c].isna() | (raw[c].str.strip() == "")).sum()) for c in raw.columns}

    expected = list(cfg["sources"]["hdb_resale"]["expected_columns"])
    source_columns = [c for c in bronze.columns if not c.startswith("_")]
    missing_columns = [c for c in expected if c not in source_columns]
    unexpected_columns = [c for c in source_columns if c not in expected]

    def check(name: str, description: str, failed: int) -> dict[str, Any]:
        return {"name": name, "description": description, "failed_rows": int(failed), "passed": int(failed) == 0}

    checks = [
        check("schema", "All expected source columns are present", len(missing_columns)),
        check("price_positive", "resale_price > 0", reason_counts.get("non_positive_price", 0)),
        check(
            "floor_area_valid",
            "floor_area_sqm > 0 and within plausible bounds",
            reason_counts.get("non_positive_floor_area", 0) + reason_counts.get("implausible_floor_area", 0),
        ),
        check("month_parseable", "month parses as YYYY-MM", reason_counts.get("unparseable_month", 0)),
        check("no_future_dates", "no transaction dated after the pull date", reason_counts.get("future_month", 0)),
        check("town_present", "town is not missing", reason_counts.get("missing_town", 0)),
        check("flat_type_present", "flat_type is not missing", reason_counts.get("missing_flat_type", 0)),
        check("lease_possible", "remaining lease within 0-99 years, commencement year plausible", reason_counts.get("impossible_lease", 0)),
        check("storey_parseable", "storey_range parses as 'NN TO NN'", reason_counts.get("unparseable_storey_range", 0)),
    ]

    valid_months = silver.loc[silver["is_valid"], "month"]
    return {
        "total_rows": total,
        "valid_rows": valid,
        "invalid_rows": total - valid,
        "valid_pct": round(100.0 * valid / total, 3) if total else None,
        "invalid_by_reason": reason_counts,
        "duplicate_rows": int(silver["is_duplicate"].sum()),
        "price_outlier_rows": int(silver["is_price_outlier"].sum()),
        "lease_mismatch_rows": int(silver["lease_mismatch"].sum()),
        "lease_derived_rows": int((silver["remaining_lease_source"] == "derived").sum()),
        "excluded_from_model_rows": int(silver["exclude_from_model"].sum()),
        "excluded_from_model_by_reason": {
            k: int(v) for k, v in silver.loc[silver["exclude_from_model"], "model_exclusion_reason"].value_counts().items()
        },
        "missing_values": missing_by_column,
        "missing_values_total": int(sum(missing_by_column.values())),
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "earliest_month": valid_months.min().strftime("%Y-%m") if len(valid_months) else None,
        "latest_month": valid_months.max().strftime("%Y-%m") if len(valid_months) else None,
        "towns": int(silver["town"].nunique()),
        "flat_types": int(silver["flat_type"].nunique()),
        "checks": checks,
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "ingested_at": ingestion.get("ingested_at"),
        "ingestion_method": ingestion.get("method"),
        "source_last_updated": ingestion.get("source_last_updated"),
        "api_total_rows": ingestion.get("api_total_rows"),
        "snapshot_sha256": ingestion.get("snapshot_sha256"),
        "ingestion_notes": ingestion.get("notes", []),
    }
