"""Load the serving bundle the pipeline publishes.

Locally the bundle is a folder (data/serving). On Databricks Apps it lives in a
Unity Catalog volume and is copied to local disk once at start-up, so every
request is served from memory with no warehouse round trip.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from flatfair.config import REPO_ROOT

log = logging.getLogger(__name__)

REQUIRED_FILES = ["meta.json", "transactions.parquet", "market_monthly.parquet", "town_summary.parquet", "forecast.parquet", "fair_value_model.joblib"]
RARE_FLAT_TYPES = {"1 ROOM", "MULTI-GENERATION"}
FLAT_TYPE_ORDER = ["2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "1 ROOM", "MULTI-GENERATION"]


class BundleError(RuntimeError):
    """The serving bundle is missing or incomplete."""


def _download_volume(volume_path: str) -> Path:
    """Copy every file in a UC volume folder to a temp dir via the Files API."""
    from databricks.sdk import WorkspaceClient  # available inside Databricks Apps

    client = WorkspaceClient()
    target = Path(tempfile.mkdtemp(prefix="flatfair_serving_"))
    count = 0
    for entry in client.files.list_directory_contents(volume_path):
        if entry.is_directory:
            continue
        response = client.files.download(entry.path)
        with (target / entry.name).open("wb") as handle:
            shutil.copyfileobj(response.contents, handle)
        count += 1
    log.info("Downloaded %d serving files from %s", count, volume_path)
    return target


def resolve_serving_dir() -> Path:
    volume = os.environ.get("FLATFAIR_SERVING_VOLUME")
    if volume:
        return _download_volume(volume)
    return Path(os.environ.get("FLATFAIR_SERVING_DIR", REPO_ROOT / "data" / "serving"))


@dataclass
class Bundle:
    meta: dict[str, Any]
    transactions: pd.DataFrame
    market_monthly: pd.DataFrame
    town_summary: pd.DataFrame
    forecast: pd.DataFrame
    income: pd.DataFrame | None
    model: Any
    last_month: pd.Timestamp = field(init=False)
    towns: list[str] = field(init=False)
    flat_types: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.last_month = pd.Timestamp(self.meta["last_complete_month"] + "-01")
        self.towns = sorted(self.transactions["town"].dropna().unique().tolist())
        present = set(self.transactions["flat_type"].dropna().unique())
        self.flat_types = [t for t in FLAT_TYPE_ORDER if t in present] + sorted(present - set(FLAT_TYPE_ORDER))
        # Analytics use complete months only; comparables may use the open month too.
        self.complete = self.transactions[self.transactions["month"] <= self.last_month]

    @property
    def common_flat_types(self) -> list[str]:
        return [t for t in self.flat_types if t not in RARE_FLAT_TYPES]

    @property
    def income_benchmark(self) -> dict[str, Any] | None:
        if self.income is None or self.income.empty:
            return None
        latest = self.income.sort_values("year").iloc[-1]
        return {
            "year": int(latest["year"]),
            "monthly_income": float(latest["median_monthly_household_income"]),
            "series": str(latest["series_name"]),
            "table_id": str(latest["table_id"]),
            "table_title": str(latest.get("table_title", "")),
        }


def load_bundle(serving_dir: Path | None = None) -> Bundle:
    serving_dir = Path(serving_dir or resolve_serving_dir())
    missing = [name for name in REQUIRED_FILES if not (serving_dir / name).exists()]
    if missing:
        raise BundleError(
            f"Serving bundle at {serving_dir} is missing {missing}. Run `python run_pipeline.py` "
            "(locally) or the Databricks notebooks first."
        )
    meta = json.loads((serving_dir / "meta.json").read_text(encoding="utf-8"))
    frames = {}
    for name in ("transactions", "market_monthly", "town_summary", "forecast"):
        frame = pd.read_parquet(serving_dir / f"{name}.parquet")
        for column in ("month", "origin_month", "as_of_month"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column])
        frames[name] = frame
    income_path = serving_dir / "income.parquet"
    income = pd.read_parquet(income_path) if income_path.exists() else None
    model = joblib.load(serving_dir / "fair_value_model.joblib")
    bundle = Bundle(meta=meta, income=income, model=model, **frames)
    log.info("Loaded serving bundle from %s (%s transactions)", serving_dir, f"{len(bundle.transactions):,}")
    return bundle
