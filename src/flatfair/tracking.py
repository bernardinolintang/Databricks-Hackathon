"""MLflow logging for both models. Modelling code stays free of MLflow imports."""

from __future__ import annotations

import inspect
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.exceptions import MlflowException

from flatfair.config import local_data_dir
from flatfair.models.fair_value import FairValueResult
from flatfair.models.forecast import ForecastResult

log = logging.getLogger(__name__)


def on_databricks() -> bool:
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def configure_mlflow(cfg: dict[str, Any]) -> str:
    """Point MLflow at the workspace on Databricks, or a local SQLite store."""
    if on_databricks():
        mlflow.set_tracking_uri("databricks")
        mlflow.set_registry_uri("databricks-uc")
        experiment = cfg["mlflow"]["experiment_databricks"]
        mlflow.set_experiment(experiment)
        return experiment

    if os.environ.get("MLFLOW_TRACKING_URI"):
        mlflow.set_experiment(cfg["mlflow"]["experiment_local"])
        return cfg["mlflow"]["experiment_local"]

    store = local_data_dir(cfg) / "mlflow"
    store.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{(store / 'mlflow.db').as_posix()}")
    experiment = cfg["mlflow"]["experiment_local"]
    if mlflow.get_experiment_by_name(experiment) is None:
        mlflow.create_experiment(experiment, artifact_location=(store / "artifacts").as_uri())
    mlflow.set_experiment(experiment)
    return experiment


# Newer MLflow saves scikit-learn models with skops, which refuses types it has
# not been told to trust. These are the ones our own HistGradientBoosting
# pipelines contain; the models are trained in this process, not loaded from
# anywhere else.
SKOPS_TRUSTED_TYPES = [
    "functools.partial",
    "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
    "sklearn.utils.validation.check_array",
]


def _log_sklearn_model(model: Any, name: str, input_example: pd.DataFrame, registered_name: str | None = None) -> None:
    """Log a model across MLflow 2 and 3, whose `log_model` signatures differ."""
    parameters = inspect.signature(mlflow.sklearn.log_model).parameters
    # `artifact_path` was renamed `name` in MLflow 3.
    key = "name" if "name" in parameters else "artifact_path"
    kwargs: dict[str, Any] = {key: name, "input_example": input_example}
    if "skops_trusted_types" in parameters:
        kwargs["skops_trusted_types"] = SKOPS_TRUSTED_TYPES
    try:
        mlflow.sklearn.log_model(model, registered_model_name=registered_name, **kwargs)
    except MlflowException as exc:
        if registered_name is None:
            raise
        # Registration needs Unity Catalog privileges the tracking run does not.
        # Keep the logged model and say so rather than failing the pipeline.
        log.warning("Model registration as '%s' failed (%s); logging without registering", registered_name, exc)
        mlflow.sklearn.log_model(model, **kwargs)


def _log_frame(frame: pd.DataFrame, filename: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        frame.to_csv(path, index=False)
        mlflow.log_artifact(str(path), artifact_path="tables")


def log_forecast(result: ForecastResult, cfg: dict[str, Any]) -> str:
    """One parent run for the backtest, one child run per method."""
    info = result.info
    with mlflow.start_run(run_name="forecast_backtest") as parent:
        mlflow.set_tags({"flatfair.module": "forecast", "flatfair.selected_method": result.selected_method})
        mlflow.log_params(
            {
                "horizon_months": info["horizon_months"],
                "backtest_folds": cfg["forecast"]["backtest_folds"],
                "backtest_step_months": cfg["forecast"]["backtest_step_months"],
                "series_count": info["series_count"],
                "training_period": " to ".join(info["training_period"]),
                "validation_period": " to ".join(info["validation_period"]),
                "validation_origins": ",".join(info["validation_origins"]),
                "interval_level": info["interval_level"],
                "selection_metric": "mape",
            }
        )
        for row in result.metrics.itertuples(index=False):
            with mlflow.start_run(run_name=f"forecast_{row.method}", nested=True):
                mlflow.set_tags({"flatfair.module": "forecast", "flatfair.method": row.method, "flatfair.selected": str(bool(row.selected))})
                mlflow.log_metrics({"mae": row.mae, "rmse": row.rmse, "mape": row.mape, "n_forecasts": row.n})
                by_horizon = result.metrics_by_horizon[result.metrics_by_horizon["method"] == row.method]
                for h in by_horizon.itertuples(index=False):
                    mlflow.log_metric("mape_by_horizon", h.mape, step=int(h.horizon))
                    mlflow.log_metric("mae_by_horizon", h.mae, step=int(h.horizon))
                if row.method == "gbm":
                    mlflow.log_params({f"gbm_{k}": v for k, v in cfg["forecast"]["gbm"].items()})
                    mlflow.log_param("feature_set", ",".join(info["feature_columns"]))
                    example = result.features[info["feature_columns"]].dropna().head(5)
                    _log_sklearn_model(result.model, "model", example)
        selected = result.metrics[result.metrics["selected"]].iloc[0]
        mlflow.log_metrics({"selected_mae": selected.mae, "selected_rmse": selected.rmse, "selected_mape": selected.mape})
        _log_frame(result.metrics, "forecast_metrics.csv")
        _log_frame(result.metrics_by_horizon, "forecast_metrics_by_horizon.csv")
        _log_frame(result.intervals, "forecast_intervals.csv")
        return parent.info.run_id


def log_fair_value(result: FairValueResult, cfg: dict[str, Any], example: pd.DataFrame) -> str:
    info = result.info
    registered = cfg["mlflow"]["registered_model_fair_value"]
    if on_databricks():
        registered = f"{cfg['storage']['catalog']}.{cfg['storage']['schema']}.{registered}"
    with mlflow.start_run(run_name="fair_value_training") as parent:
        mlflow.set_tags({"flatfair.module": "fair_value", "flatfair.selected_model": result.selected_model})
        mlflow.log_params(
            {
                "target": info["target"],
                "feature_set": ",".join(info["features"]),
                "training_period": " to ".join(info["training_period"]),
                "validation_period": " to ".join(info["holdout_period"]),
                "train_rows": info["train_rows"],
                "holdout_rows": info["holdout_rows"],
                "excluded_flat_types": ",".join(info["excluded_flat_types"]),
                "interval_level": info["interval_level"],
                "selection_metric": "mae",
            }
        )
        for row in result.metrics.itertuples(index=False):
            with mlflow.start_run(run_name=f"fair_value_{row.model}", nested=True):
                mlflow.set_tags({"flatfair.module": "fair_value", "flatfair.model": row.model, "flatfair.selected": str(bool(row.selected))})
                mlflow.log_metrics(
                    {
                        "mae": row.mae,
                        "rmse": row.rmse,
                        "mape": row.mape,
                        "median_ape": row.median_ape,
                        "within_5pct": row.within_5pct,
                        "within_10pct": row.within_10pct,
                    }
                )
                if row.model.startswith("gradient_boosting"):
                    mlflow.log_params({f"gbm_{k}": v for k, v in cfg["fair_value"]["gbm"].items()})
                if row.model == "ridge":
                    mlflow.log_param("ridge_alpha", cfg["fair_value"]["ridge_alpha"])
        selected = result.metrics[result.metrics["selected"]].iloc[0]
        mlflow.log_metrics({"selected_mae": selected.mae, "selected_rmse": selected.rmse, "selected_mape": selected.mape})
        _log_frame(result.metrics, "fair_value_metrics.csv")
        _log_frame(result.importance, "fair_value_importance.csv")
        _log_frame(result.intervals, "fair_value_intervals.csv")
        # The served model: refitted on all data after selection.
        _log_sklearn_model(result.model, "model", example, registered_name=registered)
        return parent.info.run_id
