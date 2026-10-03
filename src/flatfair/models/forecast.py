"""Six-month forecast of monthly median resale price per town x flat type.

Four methods are compared with a rolling-origin backtest (never a random
split: shuffling a time series lets the model see the future):

  naive_last     the latest monthly median carried forward
  rolling_3m     the average of the last three monthly medians   (baseline)
  linear_trend   a straight line through the last 24 months
  gbm            one gradient-boosted model shared by every series, predicting
                 the change from the recent level using lag and momentum features

The method with the lowest backtest MAPE is used for the published forecast, and
its backtest errors supply the prediction interval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from flatfair.features.market import ALL

METHODS = ["naive_last", "rolling_3m", "linear_trend", "gbm"]
BASELINE_METHOD = "rolling_3m"
TREND_WINDOW = 24
CATEGORICAL_FEATURES = ["town_code", "flat_type_code"]
# Series are grouped by how many sales they see a month; thin series are noisier
# and deserve a wider interval.
VOLUME_TIERS = [(0, 10, "under 10 sales a month"), (10, 30, "10-30 sales a month"), (30, np.inf, "30+ sales a month")]


def feature_columns(cfg: dict[str, Any]) -> list[str]:
    lags = cfg["forecast"]["lags"]
    return (
        ["dev_1"]
        + [f"ret_{k}" for k in lags]
        + ["ma3_vs_ma6", "ma3_vs_ma12", "trend_slope", "log_vol_3m", "vol_yoy", "nat_ret_3", "nat_ret_12"]
        + ["horizon", "target_moy"]
        + CATEGORICAL_FEATURES
    )


@dataclass
class ForecastResult:
    features: pd.DataFrame
    backtest: pd.DataFrame
    metrics: pd.DataFrame
    metrics_by_horizon: pd.DataFrame
    intervals: pd.DataFrame
    forecast: pd.DataFrame
    selected_method: str
    model: Any
    info: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Series preparation and features
# --------------------------------------------------------------------------- #
def prepare_series(market_monthly: pd.DataFrame, cfg: dict[str, Any]) -> dict[tuple[str, str], pd.DataFrame]:
    """Pick the series with enough history and return log-price frames.

    A month with fewer than `min_transactions_for_stat` sales does not give a
    trustworthy median, so it is treated as unobserved: carried forward from the
    previous month for lag features (never interpolated, which would borrow
    from the future), and never used as a training target or a backtest actual.
    """
    fc = cfg["forecast"]
    min_txn = cfg["market"]["min_transactions_for_stat"]
    series: dict[tuple[str, str], pd.DataFrame] = {}
    for (town, flat_type), group in market_monthly.groupby(["town", "flat_type"], observed=True):
        group = group.set_index("month").sort_index()
        price = group["median_price"].where(group["transactions"] >= min_txn)
        if price.notna().sum() < fc["min_history_months"]:
            continue
        if group["transactions"].iloc[-12:].sum() < fc["min_recent_transactions"]:
            continue
        if price.iloc[-12:].isna().sum() > 2:
            continue
        log_price = np.log(price)
        frame = pd.DataFrame(
            {
                "y": log_price.ffill(),
                "y_observed": log_price,
                "vol": group["transactions"].astype(float),
            }
        )
        series[(town, flat_type)] = frame.loc[frame["y"].first_valid_index():]
    if (ALL, ALL) not in series:
        raise ValueError("The national series is missing; cannot build market-wide features")
    return series


def _rolling_trend(y: pd.Series, window: int = TREND_WINDOW) -> tuple[pd.Series, pd.Series]:
    """Slope and end-of-window fitted value of an OLS line over the last `window` months."""
    x = np.arange(window) - (window - 1) / 2.0
    sxx = float((x**2).sum())
    slope = y.rolling(window).apply(lambda values: float(np.dot(x, values)) / sxx, raw=True)
    fitted_end = y.rolling(window).mean() + slope * (window - 1) / 2.0
    return slope, fitted_end


def _series_features(frame: pd.DataFrame, national: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    y = frame["y"]
    feats = pd.DataFrame(index=frame.index)
    feats["y"] = y
    feats["level"] = y.rolling(3).mean()
    feats["dev_1"] = y - feats["level"]
    for k in cfg["forecast"]["lags"]:
        feats[f"ret_{k}"] = y - y.shift(k)
    feats["ma3_vs_ma6"] = feats["level"] - y.rolling(6).mean()
    feats["ma3_vs_ma12"] = feats["level"] - y.rolling(12).mean()
    feats["trend_slope"], feats["trend_fit"] = _rolling_trend(y)
    vol_3m = np.log1p(frame["vol"].rolling(3).mean())
    feats["vol_3m"] = frame["vol"].rolling(3).mean()
    feats["log_vol_3m"] = vol_3m
    feats["vol_yoy"] = vol_3m - vol_3m.shift(12)
    nat = national["y"].reindex(frame.index)
    feats["nat_ret_3"] = nat - nat.shift(3)
    feats["nat_ret_12"] = nat - nat.shift(12)
    return feats


def build_features(series: dict[tuple[str, str], pd.DataFrame], cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per (series, origin month, horizon). `target` is the change in log
    price from the origin's 3-month level to the month being forecast."""
    horizon = cfg["forecast"]["horizon_months"]
    max_lag = max(cfg["forecast"]["lags"])
    national = series[(ALL, ALL)]
    towns = sorted({town for town, _ in series})
    flat_types = sorted({flat_type for _, flat_type in series})
    town_code = {name: i for i, name in enumerate(towns)}
    type_code = {name: i for i, name in enumerate(flat_types)}

    rows = []
    for (town, flat_type), frame in series.items():
        feats = _series_features(frame, national, cfg)
        feats = feats[feats[f"ret_{max_lag}"].notna()]
        for h in range(1, horizon + 1):
            part = feats.copy()
            part["horizon"] = h
            part["target_month"] = part.index + pd.DateOffset(months=h)
            part["y_target"] = frame["y_observed"].shift(-h).reindex(part.index)
            part["target"] = part["y_target"] - part["level"]
            rows.append(part.assign(town=town, flat_type=flat_type).rename_axis("origin_month").reset_index())
    features = pd.concat(rows, ignore_index=True)
    features["target_moy"] = features["target_month"].dt.month
    features["town_code"] = features["town"].map(town_code)
    features["flat_type_code"] = features["flat_type"].map(type_code)
    return features


# --------------------------------------------------------------------------- #
# Methods
# --------------------------------------------------------------------------- #
def _fit_gbm(train: pd.DataFrame, cfg: dict[str, Any]) -> HistGradientBoostingRegressor:
    params = cfg["forecast"]["gbm"]
    model = HistGradientBoostingRegressor(
        loss="absolute_error",  # median-like fit; a few wild months should not steer it
        max_iter=params["max_iter"],
        learning_rate=params["learning_rate"],
        max_depth=params["max_depth"],
        min_samples_leaf=params["min_samples_leaf"],
        l2_regularization=params["l2_regularization"],
        categorical_features=CATEGORICAL_FEATURES,
        random_state=cfg["forecast"]["random_state"],
    )
    return model.fit(train[feature_columns(cfg)], train["target"])


def _predict_all(rows: pd.DataFrame, model: HistGradientBoostingRegressor, cfg: dict[str, Any]) -> pd.DataFrame:
    """Log-price predictions from every method for the given feature rows."""
    out = pd.DataFrame(index=rows.index)
    out["naive_last"] = rows["y"]
    out["rolling_3m"] = rows["level"]
    out["linear_trend"] = rows["trend_fit"] + rows["trend_slope"] * rows["horizon"]
    out["gbm"] = rows["level"] + model.predict(rows[feature_columns(cfg)])
    return out


def _volume_tier(vol_3m: pd.Series) -> pd.Series:
    tier = pd.Series("", index=vol_3m.index, dtype=object)
    for low, high, label in VOLUME_TIERS:
        tier[(vol_3m >= low) & (vol_3m < high)] = label
    return tier


def _score(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    error = predicted - actual
    return {
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "mape": float((error.abs() / actual).mean() * 100),
        "n": int(len(actual)),
    }


def backtest_origins(last_month: pd.Timestamp, cfg: dict[str, Any]) -> list[pd.Timestamp]:
    fc = cfg["forecast"]
    newest = last_month - pd.DateOffset(months=fc["horizon_months"])
    return sorted(newest - pd.DateOffset(months=fc["backtest_step_months"] * k) for k in range(fc["backtest_folds"]))


def run_backtest(features: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Rolling-origin evaluation. For each origin T the model is trained only on
    targets observed up to T, then asked to forecast T+1 ... T+6."""
    last_month = features["origin_month"].max()
    labelled = features[features["target"].notna()]
    results = []
    for origin in backtest_origins(last_month, cfg):
        train = labelled[labelled["target_month"] <= origin]
        test = labelled[labelled["origin_month"] == origin]
        if train.empty or test.empty:
            raise ValueError(f"Backtest fold at {origin:%Y-%m} has no data; reduce backtest_folds")
        model = _fit_gbm(train, cfg)
        predictions = np.exp(_predict_all(test, model, cfg))
        fold = test[["town", "flat_type", "origin_month", "target_month", "horizon", "vol_3m"]].copy()
        fold["actual"] = np.exp(test["y_target"])
        for method in METHODS:
            fold[f"pred_{method}"] = predictions[method]
        fold["train_rows"] = len(train)
        results.append(fold)
    backtest = pd.concat(results, ignore_index=True)
    backtest["volume_tier"] = _volume_tier(backtest["vol_3m"])
    return backtest


def summarise_backtest(backtest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    overall = pd.DataFrame([{"method": m, **_score(backtest["actual"], backtest[f"pred_{m}"])} for m in METHODS])
    baseline_mape = overall.loc[overall["method"] == BASELINE_METHOD, "mape"].iloc[0]
    overall["mape_vs_baseline_pct"] = ((overall["mape"] / baseline_mape - 1) * 100).round(2)
    by_horizon = pd.DataFrame(
        [
            {"method": m, "horizon": int(h), **_score(group["actual"], group[f"pred_{m}"])}
            for m in METHODS
            for h, group in backtest.groupby("horizon")
        ]
    )
    return overall, by_horizon


def build_intervals(backtest: pd.DataFrame, method: str, cfg: dict[str, Any]) -> pd.DataFrame:
    """Empirical prediction interval: the central `interval_level` share of
    backtest errors (as log ratios) for each horizon and volume tier."""
    level = cfg["forecast"]["interval_level"]
    lower_q, upper_q = (1 - level) / 2, 1 - (1 - level) / 2
    errors = backtest.assign(log_error=np.log(backtest["actual"] / backtest[f"pred_{method}"]))
    rows = []
    for horizon, by_horizon in errors.groupby("horizon"):
        for _, _, tier in VOLUME_TIERS:
            sample = by_horizon.loc[by_horizon["volume_tier"] == tier, "log_error"]
            # Too few errors to trust a tail quantile: fall back to the whole horizon.
            pooled = len(sample) < 30
            if pooled:
                sample = by_horizon["log_error"]
            rows.append(
                {
                    "horizon": int(horizon),
                    "volume_tier": tier,
                    "lower_log": float(sample.quantile(lower_q)),
                    "upper_log": float(sample.quantile(upper_q)),
                    "n_errors": int(len(sample)),
                    "pooled_across_tiers": pooled,
                }
            )
    return pd.DataFrame(rows)


def run_forecast(market_monthly: pd.DataFrame, cfg: dict[str, Any]) -> ForecastResult:
    series = prepare_series(market_monthly, cfg)
    features = build_features(series, cfg)
    backtest = run_backtest(features, cfg)
    metrics, by_horizon = summarise_backtest(backtest)
    selected = metrics.sort_values("mape").iloc[0]["method"]
    metrics["selected"] = metrics["method"] == selected
    intervals = build_intervals(backtest, selected, cfg)

    labelled = features[features["target"].notna()]
    final_model = _fit_gbm(labelled, cfg)
    last_month = features["origin_month"].max()
    latest = features[features["origin_month"] == last_month].copy()
    predictions = _predict_all(latest, final_model, cfg)
    latest["volume_tier"] = _volume_tier(latest["vol_3m"])
    latest = latest.merge(intervals, on=["horizon", "volume_tier"], how="left")
    log_forecast = predictions[selected].to_numpy()
    forecast = pd.DataFrame(
        {
            "town": latest["town"],
            "flat_type": latest["flat_type"],
            "origin_month": latest["origin_month"],
            "month": latest["target_month"],
            "horizon": latest["horizon"],
            "forecast_price": np.exp(log_forecast).round(-3),
            "lower_price": np.exp(log_forecast + latest["lower_log"]).round(-3),
            "upper_price": np.exp(log_forecast + latest["upper_log"]).round(-3),
            "recent_level_price": np.exp(latest["level"]).round(-3),
            "volume_tier": latest["volume_tier"],
            "method": selected,
        }
    ).sort_values(["town", "flat_type", "horizon"]).reset_index(drop=True)

    origins = backtest_origins(last_month, cfg)
    info = {
        "selected_method": selected,
        "baseline_method": BASELINE_METHOD,
        "series_count": len(series),
        "feature_columns": feature_columns(cfg),
        "training_period": [features["origin_month"].min().strftime("%Y-%m"), last_month.strftime("%Y-%m")],
        "validation_origins": [o.strftime("%Y-%m") for o in origins],
        "validation_period": [
            (origins[0] + pd.DateOffset(months=1)).strftime("%Y-%m"),
            last_month.strftime("%Y-%m"),
        ],
        "horizon_months": cfg["forecast"]["horizon_months"],
        "interval_level": cfg["forecast"]["interval_level"],
        "backtest_rows": int(len(backtest)),
        "train_rows": int(len(labelled)),
    }
    return ForecastResult(features, backtest, metrics, by_horizon, intervals, forecast, selected, final_model, info)

