"""Fair value model: what similar flats have sold for, adjusted to today's market.

The model predicts log(resale_price / market_index), where the market index is
the national median price per sqm over the preceding months. Dividing by the
index removes the market-wide price level, so the model learns how *attributes*
move price (town, size, lease, storey) and an estimate for today is simply
re-inflated with the latest index. Tree models cannot extrapolate a time trend
on their own; this is what keeps the estimate current.

Evaluation holds out the most recent months. Because the index for a month uses
only earlier months, the held-out prices never leak into their own prediction.

When block locations are available the model also learns from what is near the
block: the walk to the MRT, shops, food, parks, schools and buses. The same
model without those inputs is scored beside it, so what location adds is
measured and not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, PolynomialFeatures, StandardScaler

from flatfair.features.location import LOCATION_FEATURES, LOCATION_LABELS

CATEGORICAL = ["town", "flat_type", "flat_model"]
NUMERIC = ["floor_area_sqm", "storey_mid", "remaining_lease_years", "months_since_start"]
FEATURES = CATEGORICAL + NUMERIC
# What a user supplies; months_since_start is filled in by the service.
INPUT_FEATURES = ["town", "flat_type", "flat_model", "floor_area_sqm", "storey_mid", "remaining_lease_years"]
FEATURE_LABELS = {
    "town": "Town",
    "flat_type": "Flat type",
    "flat_model": "Flat model",
    "floor_area_sqm": "Floor area",
    "storey_mid": "Storey",
    "remaining_lease_years": "Remaining lease",
    "months_since_start": "Transaction date",
    **LOCATION_LABELS,
}
MODEL_NAMES = ["comparable_median", "ridge", "gradient_boosting"]
BASELINE_MODEL = "comparable_median"
# Gradient boosting on the flat's own details only: the yardstick for what location adds.
FLAT_ONLY_MODEL = "gradient_boosting_flat_only"


@dataclass
class FairValueResult:
    model: Pipeline
    metrics: pd.DataFrame
    selected_model: str
    intervals: pd.DataFrame
    importance: pd.DataFrame
    holdout_predictions: pd.DataFrame
    info: dict[str, Any] = field(default_factory=dict)
    # A few training rows in the shape the served model expects (for MLflow).
    example: pd.DataFrame | None = None


def coerce_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Fix feature dtypes at the model boundary.

    Training and serving must hand the model identical dtypes. A pandas
    nullable column (silver's Int64) turns the whole matrix into `object`
    during training, and a model fitted that way fails on plain floats later.
    """
    out = frame.copy()
    for column in CATEGORICAL:
        out[column] = out[column].astype(str)
    for column in NUMERIC + LOCATION_FEATURES:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="raise").astype("float64")
    return out


def attach_location(transactions: pd.DataFrame, block_locations: pd.DataFrame | None) -> tuple[pd.DataFrame, list[str]]:
    """Add each sale's block location features. Returns the frame and the
    features that actually carry data (a place source may have been unavailable)."""
    if block_locations is None or not {"block", "street_name"}.issubset(transactions.columns):
        return transactions, []
    present = [f for f in LOCATION_FEATURES if f in block_locations.columns and block_locations[f].notna().any()]
    if not present:
        return transactions, []
    lookup = block_locations.drop_duplicates(["block", "street_name"])[["block", "street_name", *present]]
    return transactions.merge(lookup, on=["block", "street_name"], how="left"), present


def modelling_frame(transactions: pd.DataFrame, market_index: pd.DataFrame) -> pd.DataFrame:
    """Attach the market index and the model target to transactions."""
    frame = coerce_features(transactions).merge(market_index[["month", "market_index_psm"]], on="month", how="left")
    if frame["market_index_psm"].isna().any():
        raise ValueError("Market index is missing for some transaction months")
    frame["target"] = np.log(frame["resale_price"] / frame["market_index_psm"])
    return frame


def _ridge_pipeline(cfg: dict[str, Any], numeric_features: list[str] = NUMERIC) -> Pipeline:
    numeric = Pipeline(
        [
            # A block that could not be placed has no location; ridge needs a number.
            ("fill", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("curve", PolynomialFeatures(degree=2, include_bias=False)),
        ]
    )
    prep = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("num", numeric, numeric_features),
        ]
    )
    return Pipeline([("prep", prep), ("model", Ridge(alpha=cfg["fair_value"]["ridge_alpha"]))])


def _gbm_pipeline(cfg: dict[str, Any], numeric_features: list[str] = NUMERIC) -> Pipeline:
    params = cfg["fair_value"]["gbm"]
    prep = ColumnTransformer(
        [
            # Categories unseen in training become missing, which the trees handle natively.
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), CATEGORICAL),
            ("num", "passthrough", numeric_features),
        ]
    )
    model = HistGradientBoostingRegressor(
        max_iter=params["max_iter"],
        learning_rate=params["learning_rate"],
        max_leaf_nodes=params["max_leaf_nodes"],
        min_samples_leaf=params["min_samples_leaf"],
        l2_regularization=params["l2_regularization"],
        categorical_features=list(range(len(CATEGORICAL))),
        random_state=cfg["fair_value"]["random_state"],
    )
    return Pipeline([("prep", prep), ("model", model)])


def _comparable_median_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """The estimate a careful buyer makes by hand: the recent median price per
    sqm for the same town and flat type, times the flat's floor area."""
    recent = train[train["month"] >= train["month"].max() - pd.DateOffset(months=11)]
    by_town_type = recent.groupby(["town", "flat_type"], observed=True)["price_per_sqm"].median().rename("psm")
    by_type = recent.groupby("flat_type", observed=True)["price_per_sqm"].median().rename("psm_type")
    joined = test.join(by_town_type, on=["town", "flat_type"]).join(by_type, on="flat_type")
    psm = joined["psm"].fillna(joined["psm_type"]).fillna(recent["price_per_sqm"].median())
    return (psm * test["floor_area_sqm"]).to_numpy()


def _score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    ape = np.abs(error) / actual
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "mape": float(ape.mean() * 100),
        "median_ape": float(np.median(ape) * 100),
        "within_5pct": float((ape <= 0.05).mean() * 100),
        "within_10pct": float((ape <= 0.10).mean() * 100),
        "n": int(len(actual)),
    }


def model_features(model: Pipeline) -> list[str]:
    """The columns a fitted model was trained on, in order."""
    return list(model.feature_names_in_)


def _to_price(model: Pipeline, frame: pd.DataFrame) -> np.ndarray:
    return np.exp(model.predict(frame[model_features(model)])) * frame["market_index_psm"].to_numpy()


def train_fair_value(
    silver: pd.DataFrame,
    market_index: pd.DataFrame,
    last_month: pd.Timestamp,
    cfg: dict[str, Any],
    block_locations: pd.DataFrame | None = None,
) -> FairValueResult:
    fv = cfg["fair_value"]
    # `exclude_from_model` covers invalid records and flat types too sparse to
    # model; flagged price outliers are deliberately kept (see clean.py).
    usable = silver[~silver["exclude_from_model"] & (silver["month"] <= last_month)]
    usable, location = attach_location(usable, block_locations)
    frame = modelling_frame(usable, market_index)
    features = FEATURES + location

    holdout_start = last_month - pd.DateOffset(months=fv["holdout_months"] - 1)
    train = frame[frame["month"] < holdout_start]
    holdout = frame[frame["month"] >= holdout_start]
    if train.empty or holdout.empty:
        raise ValueError("Not enough data to split fair value training and holdout sets")

    candidates = {"ridge": _ridge_pipeline(cfg, NUMERIC + location), "gradient_boosting": _gbm_pipeline(cfg, NUMERIC + location)}
    candidate_features = {name: features for name in candidates}
    if location:
        candidates[FLAT_ONLY_MODEL] = _gbm_pipeline(cfg)
        candidate_features[FLAT_ONLY_MODEL] = FEATURES
    model_names = [BASELINE_MODEL, *candidates]
    actual = holdout["resale_price"].to_numpy()
    predictions = {"comparable_median": _comparable_median_predict(train, holdout)}
    for name, pipeline in candidates.items():
        pipeline.fit(train[candidate_features[name]], train["target"])
        predictions[name] = _to_price(pipeline, holdout)

    metrics = pd.DataFrame([{"model": name, **_score(actual, predictions[name])} for name in model_names])
    baseline_mae = metrics.loc[metrics["model"] == BASELINE_MODEL, "mae"].iloc[0]
    metrics["mae_vs_baseline_pct"] = ((metrics["mae"] / baseline_mae - 1) * 100).round(2)
    # Only a fitted model can be served; the hand-rule baseline is a yardstick.
    selected = metrics[metrics["model"].isin(candidates)].sort_values("mae").iloc[0]["model"]
    metrics["selected"] = metrics["model"] == selected

    holdout_predictions = holdout[["month", "town", "flat_type", "resale_price"]].copy()
    for name in model_names:
        holdout_predictions[f"pred_{name}"] = predictions[name]

    # Expected range: the central share of holdout errors, per flat type.
    level = fv["interval_level"]
    lower_q, upper_q = (1 - level) / 2, 1 - (1 - level) / 2
    log_error = np.log(actual / predictions[selected])
    errors = pd.DataFrame({"flat_type": holdout["flat_type"].to_numpy(), "log_error": log_error})
    interval_rows = [{"flat_type": "ALL", "lower_log": float(np.quantile(log_error, lower_q)), "upper_log": float(np.quantile(log_error, upper_q)), "n_errors": int(len(log_error))}]
    for flat_type, group in errors.groupby("flat_type"):
        if len(group) >= 100:
            interval_rows.append(
                {
                    "flat_type": flat_type,
                    "lower_log": float(group["log_error"].quantile(lower_q)),
                    "upper_log": float(group["log_error"].quantile(upper_q)),
                    "n_errors": int(len(group)),
                }
            )
    intervals = pd.DataFrame(interval_rows)

    sample = holdout.sample(min(len(holdout), fv["permutation_sample"]), random_state=fv["random_state"])
    features = candidate_features[selected]
    location = [f for f in features if f in LOCATION_FEATURES]
    permutation = permutation_importance(
        candidates[selected],
        sample[features],
        sample["target"],
        n_repeats=3,
        random_state=fv["random_state"],
        scoring="neg_mean_absolute_error",
    )
    importance = pd.DataFrame(
        {
            "feature": features,
            "label": [FEATURE_LABELS[f] for f in features],
            # Increase in mean absolute log error when the feature is shuffled.
            "importance": permutation.importances_mean,
        }
    ).sort_values("importance", ascending=False)
    importance["share_pct"] = (importance["importance"].clip(lower=0) / importance["importance"].clip(lower=0).sum() * 100).round(1)

    # Serve a model refitted on everything, so the newest sales inform estimates.
    final_train = frame
    final_model = _ridge_pipeline(cfg, NUMERIC + location) if selected == "ridge" else _gbm_pipeline(cfg, NUMERIC + location)
    final_model.fit(final_train[features], final_train["target"])

    info = {
        "selected_model": selected,
        "baseline_model": BASELINE_MODEL,
        "features": features,
        "location_features": location,
        "target": "log(resale_price / market_index_psm)",
        "training_period": [train["month"].min().strftime("%Y-%m"), train["month"].max().strftime("%Y-%m")],
        "holdout_period": [holdout["month"].min().strftime("%Y-%m"), holdout["month"].max().strftime("%Y-%m")],
        "train_rows": int(len(train)),
        "holdout_rows": int(len(holdout)),
        "final_train_rows": int(len(final_train)),
        "excluded_flat_types": list(fv["excluded_flat_types"]),
        "price_outliers_kept": int(frame["is_price_outlier"].sum()),
        "interval_level": level,
    }
    return FairValueResult(final_model, metrics, selected, intervals, importance, holdout_predictions, info, example=final_train[features].head(5))


def predict_price(model: Pipeline, flats: pd.DataFrame, market_index_psm: float, months_since_start: int) -> np.ndarray:
    """Estimate today's price for flats described by INPUT_FEATURES, plus the
    location features if the model was trained with them. A missing location
    value is allowed: the model treats it as unknown."""
    features = model_features(model)
    needed = [c for c in features if c != "months_since_start"]
    missing = [c for c in needed if c not in flats.columns]
    if missing:
        raise ValueError(f"Fair value input is missing columns: {missing}")
    frame = flats[needed].copy()
    frame["months_since_start"] = months_since_start
    return np.exp(model.predict(coerce_features(frame)[features])) * market_index_psm
