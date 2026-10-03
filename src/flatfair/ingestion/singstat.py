"""SingStat Table Builder client for the official household income benchmark."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from flatfair.ingestion.http import SourceError, get_with_retries

log = logging.getLogger(__name__)


def fetch_income_benchmark(cfg: dict[str, Any]) -> pd.DataFrame:
    """Annual median monthly household employment income, one row per year.

    Raises SourceError if the table or series is unavailable; the caller decides
    whether affordability runs without a benchmark. Values are never invented.
    """
    src = cfg["sources"]["income"]
    url = src["url"].format(table_id=src["table_id"])
    ing = cfg["ingestion"]
    response = get_with_retries(
        url,
        max_retries=ing["max_retries"],
        backoff_seconds=ing["backoff_seconds"],
        timeout_seconds=ing["timeout_seconds"],
    )
    try:
        data = response.json()["Data"]
    except (ValueError, KeyError) as exc:
        raise SourceError(f"SingStat returned an unreadable response for {src['table_id']}") from exc

    series = next((row for row in data.get("row", []) if str(row.get("seriesNo")) == str(src["series_no"])), None)
    if series is None:
        available = [f"{r.get('seriesNo')}: {r.get('rowText')}" for r in data.get("row", [])][:10]
        raise SourceError(f"Series {src['series_no']} not found in SingStat table {src['table_id']}. Available: {available}")

    frame = pd.DataFrame(series["columns"]).rename(columns={"key": "year", "value": "median_monthly_household_income"})
    frame["year"] = frame["year"].astype(int)
    frame["median_monthly_household_income"] = pd.to_numeric(frame["median_monthly_household_income"], errors="coerce")
    frame = frame.dropna(subset=["median_monthly_household_income"]).sort_values("year").reset_index(drop=True)
    frame["series_name"] = series["rowText"]
    frame["unit"] = series.get("uoM")
    frame["table_id"] = src["table_id"]
    frame["table_title"] = data.get("title")
    frame["source_last_updated"] = data.get("dataLastUpdated")
    frame["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("Income benchmark: %d years, latest %d = $%s", len(frame), frame["year"].iloc[-1], f"{frame['median_monthly_household_income'].iloc[-1]:,.0f}")
    return frame
