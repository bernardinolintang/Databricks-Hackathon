"""Sanity checks on the real serving bundle. Skipped until the pipeline has run."""

import json

import joblib
import numpy as np
import pandas as pd
import pytest

from conftest import SERVING_DIR
from flatfair.models.fair_value import attach_location, model_features, predict_price

pytestmark = pytest.mark.skipif(not (SERVING_DIR / "meta.json").exists(), reason="run the pipeline first")


@pytest.fixture(scope="module")
def meta():
    return json.loads((SERVING_DIR / "meta.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def transactions():
    return pd.read_parquet(SERVING_DIR / "transactions.parquet")


def test_no_negative_prices(transactions):
    assert (transactions["resale_price"] > 0).all()


def test_no_impossible_floor_areas(transactions):
    assert transactions["floor_area_sqm"].between(20, 400).all()


def test_no_future_transactions(transactions, meta):
    generated = pd.Timestamp(meta["generated_at"]).tz_localize(None)
    assert transactions["month"].max() <= generated


def test_forecast_within_plausible_bounds():
    forecast = pd.read_parquet(SERVING_DIR / "forecast.parquet")
    assert (forecast["lower_price"] <= forecast["forecast_price"]).all()
    assert (forecast["forecast_price"] <= forecast["upper_price"]).all()
    # Six months out, a median should not move by half.
    ratio = forecast["forecast_price"] / forecast["recent_level_price"]
    assert ratio.between(0.5, 1.5).all()


def test_fair_value_predictions_plausible(transactions, meta):
    model = joblib.load(SERVING_DIR / "fair_value_model.joblib")
    sample = transactions[transactions["month"] >= transactions["month"].max() - pd.DateOffset(months=2)]
    sample = sample[~sample["flat_type"].isin(["1 ROOM", "MULTI-GENERATION"])].sample(500, random_state=1)
    # The served model may use each block's location; give it the same inputs the app does.
    blocks = SERVING_DIR / "blocks.parquet"
    sample, _ = attach_location(sample, pd.read_parquet(blocks) if blocks.exists() else None)
    inputs = [f for f in model_features(model) if f != "months_since_start"]
    predicted = predict_price(model, sample[inputs], meta["fair_value"]["market_index_psm_now"], meta["fair_value"]["months_since_start_now"])
    assert np.all((predicted > 100_000) & (predicted < 2_500_000))
    # Recent sales should mostly sit near today's estimate.
    ape = np.abs(predicted - sample["resale_price"].to_numpy()) / sample["resale_price"].to_numpy()
    assert np.median(ape) < 0.10


def test_quality_checks_recorded(meta):
    quality = meta["quality"]
    assert quality["checks_total"] >= 9
    assert quality["valid_rows"] + quality["invalid_rows"] == quality["total_rows"]
