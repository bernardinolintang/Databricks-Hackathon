from conftest import make_bronze

from flatfair.transformation.clean import build_silver
from flatfair.transformation.quality import build_quality_summary, last_complete_month


def _silver(cfg, rows):
    return build_silver(make_bronze(rows), cfg)


def test_no_rows_are_dropped(cfg):
    rows = [{}, {"resale_price": "-5"}, {"month": "bad"}, {"town": ""}]
    silver = _silver(cfg, rows)
    assert len(silver) == len(rows)


def test_valid_row_is_typed(cfg):
    silver = _silver(cfg, [{}])
    row = silver.iloc[0]
    assert row["is_valid"]
    assert row["resale_price"] == 550000
    assert row["storey_mid"] == 8
    assert row["remaining_lease_years"] == round(65 + 3 / 12, 2)
    assert row["price_per_sqm"] == round(550000 / 92, 2)
    assert row["months_since_start"] == 84


def test_each_check_flags_its_reason(cfg):
    cases = {
        "non_positive_price": {"resale_price": "0"},
        "non_positive_floor_area": {"floor_area_sqm": "0"},
        "implausible_floor_area": {"floor_area_sqm": "900"},
        "unparseable_month": {"month": "2024/01"},
        "future_month": {"month": "2030-01"},
        "missing_town": {"town": "  "},
        "missing_flat_type": {"flat_type": ""},
        "unparseable_storey_range": {"storey_range": "HIGH"},
        "impossible_lease": {"remaining_lease": "120 years", "lease_commence_date": "1990"},
    }
    silver = _silver(cfg, list(cases.values()))
    for (reason, _), (_, row) in zip(cases.items(), silver.iterrows()):
        assert not row["is_valid"], reason
        assert reason in row["invalid_reasons"].split(";"), (reason, row["invalid_reasons"])


def test_lease_commencing_after_sale_is_impossible(cfg):
    silver = _silver(cfg, [{"lease_commence_date": "2026", "month": "2024-01"}])
    assert "impossible_lease" in silver.iloc[0]["invalid_reasons"]


def test_unreadable_lease_text_is_derived_not_dropped(cfg):
    silver = _silver(cfg, [{"remaining_lease": "n/a", "lease_commence_date": "1990", "month": "2024-01"}])
    row = silver.iloc[0]
    assert row["is_valid"]
    assert row["remaining_lease_source"] == "derived"
    assert abs(row["remaining_lease_years"] - 65) < 0.01


def test_duplicates_flagged_not_removed(cfg):
    silver = _silver(cfg, [{}, {}, {"resale_price": "560000"}])
    assert silver["is_duplicate"].tolist() == [False, True, False]
    assert silver["is_valid"].all()


def test_invalid_rows_excluded_from_model(cfg):
    silver = _silver(cfg, [{}, {"resale_price": "0"}, {"flat_type": "1 ROOM"}])
    assert silver["exclude_from_model"].tolist() == [False, True, True]
    assert silver["model_exclusion_reason"].tolist() == ["", "invalid_record", "sparse_flat_type"]


def test_quality_summary_counts(cfg):
    bronze = make_bronze([{}, {}, {"resale_price": "0"}, {"month": "2024-05"}])
    silver = build_silver(bronze, cfg)
    summary = build_quality_summary(bronze, silver, cfg)
    assert summary["total_rows"] == 4
    assert summary["invalid_rows"] == 1
    assert summary["duplicate_rows"] == 1
    assert summary["latest_month"] == "2024-05"
    assert summary["checks_total"] == len(summary["checks"])
    assert not next(c for c in summary["checks"] if c["name"] == "price_positive")["passed"]


def test_partial_month_is_not_complete(cfg):
    # Pulled mid-June 2024: June is still filling up, so May is the last complete month.
    silver = _silver(cfg, [{"month": "2024-05"}, {"month": "2024-06"}])
    assert last_complete_month(silver).strftime("%Y-%m") == "2024-05"
