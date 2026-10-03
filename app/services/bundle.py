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
from functools import cached_property
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from flatfair.config import REPO_ROOT
from flatfair.features.location import LOCATION_FEATURES, PlaceIndex, ring_metres

log = logging.getLogger(__name__)

REQUIRED_FILES = ["meta.json", "transactions.parquet", "market_monthly.parquet", "town_summary.parquet", "forecast.parquet", "fair_value_model.joblib"]
RARE_FLAT_TYPES = {"1 ROOM", "MULTI-GENERATION"}
# Location columns copied from each block onto its sales.
# `train_m` is the nearest station of either kind, MRT or LRT: what a buyer
# means by "near the train". The price model uses the MRT alone.
BLOCK_COLUMNS = ["latitude", "longitude", "train_m", *LOCATION_FEATURES]
TYPICAL_LOCATION_MONTHS = 24
NEAR_TRAIN_MINUTES = 10
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
    town_map: dict[str, Any] | None = None
    # Optional: where each block is and what is near it. Without them the app
    # still runs; it only leaves out the street map and the location inputs.
    blocks: pd.DataFrame | None = None
    places: pd.DataFrame | None = None
    connectors: pd.DataFrame | None = None
    last_month: pd.Timestamp = field(init=False)
    towns: list[str] = field(init=False)
    flat_types: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.last_month = pd.Timestamp(self.meta["last_complete_month"] + "-01")
        self.towns = sorted(self.transactions["town"].dropna().unique().tolist())
        present = set(self.transactions["flat_type"].dropna().unique())
        self.flat_types = [t for t in FLAT_TYPE_ORDER if t in present] + sorted(present - set(FLAT_TYPE_ORDER))
        if self.has_location:
            # Each sale takes its block's position, so comparables can be mapped
            # and a town's typical location worked out.
            columns = [c for c in BLOCK_COLUMNS if c in self.blocks.columns]
            lookup = self.blocks.drop_duplicates(["block", "street_name"])[["block", "street_name", *columns]]
            self.transactions = self.transactions.merge(lookup, on=["block", "street_name"], how="left")
        # Analytics use complete months only; comparables may use the open month too.
        self.complete = self.transactions[self.transactions["month"] <= self.last_month]

    @property
    def common_flat_types(self) -> list[str]:
        return [t for t in self.flat_types if t not in RARE_FLAT_TYPES]

    @property
    def has_location(self) -> bool:
        return self.blocks is not None and self.places is not None and bool(self.meta.get("location"))

    @cached_property
    def place_index(self) -> PlaceIndex:
        """Built on first use: a cold start should not pay for it."""
        return PlaceIndex(self.places, self.connectors, {"location": self.meta["location"]})

    @cached_property
    def block_flat_types(self) -> dict[tuple[str, str], list[str]]:
        """Which flat types have sold in each block."""
        pairs = self.transactions[["block", "street_name", "flat_type"]].drop_duplicates()
        order = {t: i for i, t in enumerate(self.flat_types)}
        grouped = pairs.groupby(["block", "street_name"])["flat_type"].agg(lambda s: sorted(s, key=lambda t: order.get(t, 99)))
        return grouped.to_dict()

    @cached_property
    def typical_locations(self) -> dict[tuple[str, str], dict[str, float]]:
        """The middle of each location measure over recent sales, per town and
        flat type, plus one entry per town across all flat types ('ALL')."""
        present = [f for f in ["train_m", *LOCATION_FEATURES] if f in self.transactions.columns]
        if not present:
            return {}
        recent = self.complete[self.complete["month"] > self.last_month - pd.DateOffset(months=TYPICAL_LOCATION_MONTHS)]
        near = ring_metres(NEAR_TRAIN_MINUTES, {"location": self.meta["location"]})
        out: dict[tuple[str, str], dict[str, float]] = {}

        def describe(group: pd.DataFrame) -> dict[str, float]:
            row = {f: float(group[f].median()) for f in present}
            if "train_m" in present:
                known = group["train_m"].dropna()
                row["near_train_pct"] = round(float((known <= near).mean() * 100), 0) if len(known) else None
            return row

        for (town, flat_type), group in recent.groupby(["town", "flat_type"]):
            out[(town, flat_type)] = describe(group)
        for town, group in recent.groupby("town"):
            out[(town, "ALL")] = describe(group)
        return out

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
    # Optional: without it the app offers a plain town list instead of a map.
    map_path = serving_dir / "town_map.json"
    town_map = json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else None
    optional = {}
    for name, filename in (("blocks", "blocks.parquet"), ("places", "places.parquet"), ("connectors", "park_connectors.parquet")):
        path = serving_dir / filename
        optional[name] = pd.read_parquet(path) if path.exists() else None
    bundle = Bundle(meta=meta, income=income, model=model, town_map=town_map, **optional, **frames)
    log.info("Loaded serving bundle from %s (%s transactions)", serving_dir, f"{len(bundle.transactions):,}")
    return bundle
