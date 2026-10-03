import copy

import numpy as np
import pandas as pd
import pytest

from flatfair.features.market import build_market_index, build_market_monthly
from flatfair.models.comparables import find_comparables
from flatfair.models.fair_value import INPUT_FEATURES, predict_price, train_fair_value
from flatfair.models.forecast import backtest_origins, build_features, prepare_series
from flatfair.models.interpret import interpret_forecast


@pytest.fixture
def small_cfg(cfg):
    small = copy.deepcopy(cfg)
    small["forecast"].update({"min_history_months": 24, "min_recent_transactions": 24, "backtest_folds": 2})
    small["fair_value"].update({"permutation_sample": 500})
    small["fair_value"]["gbm"].update({"max_iter": 50})
    return small


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #
def test_forecast_features_never_see_the_future(small_cfg, synthetic_transactions):
    monthly = build_market_monthly(synthetic_transactions, small_cfg)
    features = build_features(prepare_series(monthly, small_cfg), small_cfg)
    assert (features["target_month"] > features["origin_month"]).all()
    assert set(features["horizon"]) == set(range(1, small_cfg["forecast"]["horizon_months"] + 1))
    # The target is relative to the origin's level, so it reconstructs the actual.
    labelled = features.dropna(subset=["target"])
    np.testing.assert_allclose(labelled["level"] + labelled["target"], labelled["y_target"])


def test_backtest_origins_leave_room_for_horizon(cfg):
    last = pd.Timestamp("2026-09-01")
    origins = backtest_origins(last, cfg)
    assert len(origins) == cfg["forecast"]["backtest_folds"]
    assert max(origins) == last - pd.DateOffset(months=cfg["forecast"]["horizon_months"])
    assert origins == sorted(origins)


@pytest.mark.parametrize(
    "final, expected",
    [(605_000, "stable"), (630_000, "up"), (560_000, "down")],
)
def test_interpretation_direction(final, expected):
    reading = interpret_forecast("Tampines", 600_000, final, final * 0.95, final * 1.05, "Mar 2027", 0.8)
    assert reading["direction"] == expected
    assert "Tampines" in reading["headline"]
    assert "will" not in reading["headline"].lower()


def test_interpretation_flags_uncertain_direction():
    reading = interpret_forecast("Bedok", 600_000, 630_000, 580_000, 680_000, "Mar 2027", 0.8)
    assert reading["direction_uncertain"]
    assert "uncertain" in reading["caveat"]


# --------------------------------------------------------------------------- #
# Fair value
# --------------------------------------------------------------------------- #
@pytest.fixture
def trained(small_cfg, synthetic_transactions):
    index = build_market_index(synthetic_transactions, small_cfg)
    last = synthetic_transactions["month"].max()
    return train_fair_value(synthetic_transactions, index, last, small_cfg), index


def test_fair_value_beats_hand_rule_and_is_plausible(trained, synthetic_transactions):
    result, index = trained
    metrics = result.metrics.set_index("model")
    assert metrics.loc[result.selected_model, "mae"] < metrics.loc["comparable_median", "mae"]
    flats = synthetic_transactions[INPUT_FEATURES].head(20)
    prices = predict_price(result.model, flats, float(index["market_index_psm"].iloc[-1]), 48)
    assert np.all(np.isfinite(prices))
    assert np.all((prices > 100_000) & (prices < 3_000_000))


def test_fair_value_input_schema(trained):
    result, _ = trained
    with pytest.raises(ValueError, match="missing columns"):
        predict_price(result.model, pd.DataFrame([{"town": "TAMPINES"}]), 6000.0, 48)


def test_fair_value_handles_unseen_category(trained):
    result, _ = trained
    flat = pd.DataFrame([{"town": "NOWHERE", "flat_type": "4 ROOM", "flat_model": "MODEL A",
                          "floor_area_sqm": 92, "storey_mid": 8, "remaining_lease_years": 70}])
    assert np.isfinite(predict_price(result.model, flat, 6000.0, 48)[0])


def test_fair_value_interval_brackets_zero(trained):
    result, _ = trained
    overall = result.intervals.set_index("flat_type").loc["ALL"]
    assert overall["lower_log"] < 0 < overall["upper_log"]


def test_comparables_filter_and_rank(cfg, synthetic_transactions):
    comps = find_comparables(synthetic_transactions.assign(block="1", street_name="X", storey_range="07 TO 09"),
                             "TAMPINES", "4 ROOM", 92, 8, 75, cfg)
    assert len(comps) == cfg["fair_value"]["comparables"]["top_k"]
    assert (comps["town"] == "TAMPINES").all() and (comps["flat_type"] == "4 ROOM").all()
    assert comps["similarity"].is_monotonic_decreasing


def test_comparables_empty_when_no_match(cfg, synthetic_transactions):
    comps = find_comparables(synthetic_transactions.assign(block="1", street_name="X", storey_range="07 TO 09"),
                             "BEDOK", "4 ROOM", 92, 8, 75, cfg)
    assert comps.empty
