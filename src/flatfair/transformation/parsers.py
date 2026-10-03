"""Parsers for the free-text fields in the HDB resale dataset.

Each parser returns NaN/NaT for values it cannot read rather than raising, so a
single malformed row is flagged in silver instead of failing the whole run.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

# "61 years 04 months", "70 years", "61 years 1 month", or a bare number of years.
_LEASE_PATTERN = re.compile(
    r"^\s*(?P<years>\d{1,3})\s*(?:years?)?\s*(?:(?P<months>\d{1,2})\s*months?)?\s*$",
    re.IGNORECASE,
)
_STOREY_PATTERN = re.compile(r"^\s*(?P<low>\d{1,2})\s*TO\s*(?P<high>\d{1,2})\s*$", re.IGNORECASE)


def parse_remaining_lease(value: object) -> float:
    """Remaining lease in decimal years, e.g. '61 years 04 months' -> 61.33."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    match = _LEASE_PATTERN.match(str(value))
    if not match:
        return np.nan
    months = int(match.group("months") or 0)
    if months > 11:
        return np.nan
    return int(match.group("years")) + months / 12.0


def parse_storey_range(value: object) -> tuple[float, float, float]:
    """(low, high, midpoint) for a range such as '10 TO 12'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return (np.nan, np.nan, np.nan)
    match = _STOREY_PATTERN.match(str(value))
    if not match:
        return (np.nan, np.nan, np.nan)
    low, high = int(match.group("low")), int(match.group("high"))
    if low > high or low < 1:
        return (np.nan, np.nan, np.nan)
    return (float(low), float(high), (low + high) / 2.0)


def parse_month(series: pd.Series) -> pd.Series:
    """'2017-01' -> Timestamp('2017-01-01'); anything else -> NaT."""
    return pd.to_datetime(series.astype(str).str.strip(), format="%Y-%m", errors="coerce")


def standardise_text(series: pd.Series) -> pd.Series:
    """Trim, collapse internal whitespace and upper-case; empty strings become NA."""
    cleaned = series.astype("string").str.strip().str.replace(r"\s+", " ", regex=True).str.upper()
    return cleaned.replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA, "NULL": pd.NA})


def standardise_flat_type(series: pd.Series) -> pd.Series:
    """Upper-case and unify the 'MULTI GENERATION' / 'MULTI-GENERATION' spellings."""
    return standardise_text(series).str.replace("MULTI GENERATION", "MULTI-GENERATION", regex=False)
