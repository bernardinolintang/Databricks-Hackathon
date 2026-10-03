import math

import pandas as pd
import pytest

from flatfair.transformation.parsers import (
    parse_month,
    parse_remaining_lease,
    parse_storey_range,
    standardise_flat_type,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("61 years 04 months", 61 + 4 / 12),
        ("70 years", 70.0),
        ("61 years 1 month", 61 + 1 / 12),
        ("  95 years 11 months ", 95 + 11 / 12),
        ("63", 63.0),
    ],
)
def test_remaining_lease_formats(text, expected):
    assert parse_remaining_lease(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "unknown", "61 years 14 months", None, float("nan")])
def test_remaining_lease_unreadable_is_nan(text):
    assert math.isnan(parse_remaining_lease(text))


def test_storey_range():
    assert parse_storey_range("10 TO 12") == (10.0, 12.0, 11.0)
    assert parse_storey_range("01 to 03") == (1.0, 3.0, 2.0)


@pytest.mark.parametrize("text", ["12 TO 10", "GROUND", "", None])
def test_storey_range_invalid(text):
    assert all(math.isnan(v) for v in parse_storey_range(text))


def test_parse_month():
    parsed = parse_month(pd.Series(["2017-01", "2024-10", "2024-13", "Jan 2017"]))
    assert parsed.iloc[0] == pd.Timestamp("2017-01-01")
    assert parsed.iloc[1] == pd.Timestamp("2024-10-01")
    assert parsed.iloc[2:].isna().all()


def test_flat_type_spellings_unified():
    out = standardise_flat_type(pd.Series(["Multi Generation", "MULTI-GENERATION", " 4  room "]))
    assert out.tolist() == ["MULTI-GENERATION", "MULTI-GENERATION", "4 ROOM"]
