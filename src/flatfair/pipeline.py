"""The FlatFair pipeline as rerunnable steps.

    ingest     data.gov.sg + SingStat -> bronze
    transform  bronze -> silver, plus the data quality summary
    gold       silver -> market aggregates, index, affordability
    boundaries URA planning areas -> bronze, then the town map (optional)
    places     block outlines and nearby places -> where each block is and
               what is near it (optional)
    forecast   backtest and six-month forecast, logged to MLflow
    fairvalue  fair value model, logged to MLflow
    publish    gold + model -> the serving bundle the app loads

The same functions run from `run_pipeline.py` on a laptop and from the
notebooks on Databricks; only the TableStore and serving directory differ.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from flatfair import __version__
from flatfair.affordability import build_gold_affordability
from flatfair.features.market import (
    ALL,
    analysis_transactions,
    build_market_index,
    build_market_monthly,
    build_town_summary,
)
from flatfair.features.location import PlaceIndex, block_features, clean_places, match_blocks, simplify_connectors
from flatfair.features.townmap import build_town_map, town_map_frame, town_map_from_frame
from flatfair.ingestion import places as place_sources
from flatfair.ingestion.boundaries import fetch_planning_areas, planning_areas_frame
from flatfair.ingestion.datagov import ingest_hdb_resale
from flatfair.ingestion.http import SourceError
from flatfair.ingestion.singstat import fetch_income_benchmark
from flatfair.models.fair_value import train_fair_value
from flatfair.models.forecast import run_forecast
from flatfair.storage import TableStore, read_json, write_json
from flatfair.transformation.clean import build_silver, months_since_start
from flatfair.transformation.quality import build_quality_summary, last_complete_month

log = logging.getLogger(__name__)

STEPS = ["ingest", "transform", "gold", "boundaries", "places", "forecast", "fairvalue", "publish"]

# Columns the app needs from each transaction.
SERVING_TRANSACTION_COLUMNS = [
    "month", "year", "town", "flat_type", "flat_model", "block", "street_name", "storey_range",
    "storey_mid", "floor_area_sqm", "remaining_lease_years", "resale_price", "price_per_sqm",
]


def step_ingest(store: TableStore, cfg: dict[str, Any], method: str | None = None, source_csv: str | None = None) -> dict[str, Any]:
    frame, info = ingest_hdb_resale(cfg, method=method, source_csv=source_csv)
    # Full-snapshot overwrite: rerunning can never double-count transactions.
    store.write("bronze_hdb_resale", frame, mode="overwrite")
    record = info.to_dict()
    log_row = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in record.items()}
    store.write("bronze_ingestion_log", pd.DataFrame([log_row]), mode="append")

    try:
        income = fetch_income_benchmark(cfg)
    except SourceError as exc:
        # Affordability still works with user-entered income; say what is missing.
        log.warning("Income benchmark unavailable, continuing without it: %s", exc)
        record["income_benchmark"] = f"unavailable: {exc}"
    else:
        store.write("bronze_income", income, mode="overwrite")
        record["income_benchmark"] = f"{len(income)} years"
    return record


def step_transform(store: TableStore, cfg: dict[str, Any]) -> dict[str, Any]:
    bronze = store.read("bronze_hdb_resale")
    silver = build_silver(bronze, cfg)
    store.write("silver_hdb_resale", silver, mode="overwrite")

    ingestion = store.read("bronze_ingestion_log").sort_values("ingested_at").iloc[-1].to_dict()
    ingestion["notes"] = json.loads(ingestion.get("notes") or "[]")
    summary = build_quality_summary(bronze, silver, cfg, ingestion)
    summary["last_complete_month"] = last_complete_month(silver).strftime("%Y-%m")
    quality_row = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_rows": summary["total_rows"],
        "valid_rows": summary["valid_rows"],
        "invalid_rows": summary["invalid_rows"],
        "duplicate_rows": summary["duplicate_rows"],
        "missing_values_total": summary["missing_values_total"],
        "price_outlier_rows": summary["price_outlier_rows"],
        "latest_month": summary["latest_month"],
        "checks_passed": summary["checks_passed"],
        "checks_total": summary["checks_total"],
        "summary_json": json.dumps(summary, default=str),
    }
    store.write("gold_data_quality", pd.DataFrame([quality_row]), mode="overwrite")
    return summary


def _load_income(store: TableStore) -> pd.DataFrame | None:
    return store.read("bronze_income") if store.exists("bronze_income") else None


def step_gold(store: TableStore, cfg: dict[str, Any]) -> dict[str, Any]:
    silver = store.read("silver_hdb_resale")
    last_month = last_complete_month(silver)
    txn = analysis_transactions(silver, last_month)

    market_monthly = build_market_monthly(txn, cfg)
    town_summary = build_town_summary(txn, cfg)
    market_index = build_market_index(txn, cfg)
    affordability = build_gold_affordability(town_summary, _load_income(store), cfg)
    comparable = silver.loc[silver["is_valid"], SERVING_TRANSACTION_COLUMNS + ["is_duplicate", "is_price_outlier"]]

    store.write("gold_market_monthly", market_monthly)
    store.write("gold_town_summary", town_summary[town_summary["town"] != ALL])
    store.write("gold_flat_type_summary", town_summary[town_summary["town"] == ALL])
    store.write("gold_market_index", market_index)
    store.write("gold_comparable_transactions", comparable)
    if not affordability.empty:
        store.write("gold_affordability", affordability)
    return {
        "last_complete_month": last_month.strftime("%Y-%m"),
        "market_monthly_rows": len(market_monthly),
        "town_summary_rows": len(town_summary),
        "comparable_rows": len(comparable),
        "affordability_rows": len(affordability),
    }


def step_boundaries(store: TableStore, cfg: dict[str, Any], source_file: str | None = None) -> dict[str, Any]:
    """Fetch planning area shapes and build the town map.

    The map is a convenience, not a dependency: if the source is unreachable
    the app falls back to a plain town list, so this step warns and moves on.
    `source_file` reads a GeoJSON downloaded from the dataset page instead.
    """
    try:
        if source_file:
            geojson = json.loads(Path(source_file).read_text(encoding="utf-8"))
        else:
            geojson = fetch_planning_areas(cfg)
        areas = planning_areas_frame(geojson)
    except SourceError as exc:
        log.warning("Planning area boundaries unavailable, continuing without a map: %s", exc)
        return {"available": False, "reason": str(exc)}
    store.write("bronze_planning_areas", areas, mode="overwrite")

    silver = store.read("silver_hdb_resale")
    towns = sorted(silver.loc[silver["is_valid"], "town"].dropna().unique().tolist())
    town_map = build_town_map(areas, towns, cfg)
    if town_map["missing_towns"]:
        log.warning("No planning area shape for towns: %s", town_map["missing_towns"])
    store.write("gold_town_map", town_map_frame(town_map), mode="overwrite")
    return {
        "available": True,
        "planning_areas": len(areas),
        "towns_drawn": len(town_map["towns"]),
        "missing_towns": town_map["missing_towns"],
        "points": town_map["points"],
    }


def step_places(store: TableStore, cfg: dict[str, Any], fetch: bool = True) -> dict[str, Any]:
    """Place every block on the map and measure what is near it.

    Like the town map, this adds to the app without being needed by it: if the
    block outlines cannot be fetched the step warns and moves on, the price
    model trains without location and the app hides its street map.
    `fetch=False` rebuilds from the bronze tables of an earlier run.
    """
    notes: list[str] = []
    if fetch:
        try:
            buildings = place_sources.fetch_buildings(cfg)
        except SourceError as exc:
            log.warning("HDB building outlines unavailable, continuing without block locations: %s", exc)
            return {"available": False, "reason": str(exc)}
        store.write("bronze_hdb_buildings", buildings, mode="overwrite")
        # Schools already placed on an earlier run are not looked up again.
        known = {}
        if store.exists("bronze_places"):
            earlier = store.read("bronze_places")
            schools = earlier[earlier["category"] == "school"]
            known = {row.detail: (row.latitude, row.longitude) for row in schools.itertuples(index=False)}
        places, connectors, notes = place_sources.fetch_places(cfg, known_schools=known)
        store.write("bronze_places", places, mode="overwrite")
        store.write("bronze_park_connectors", connectors, mode="overwrite")
    elif not store.exists("bronze_hdb_buildings"):
        return {"available": False, "reason": "no block outlines from an earlier run"}

    buildings = store.read("bronze_hdb_buildings")
    places = clean_places(store.read("bronze_places"))
    connectors = simplify_connectors(store.read("bronze_park_connectors"), cfg)

    silver = store.read("silver_hdb_resale")
    valid = silver[silver["is_valid"]]
    addresses = valid.groupby(["town", "block", "street_name"], as_index=False).agg(
        sales=("resale_price", "size"), lease_commence_year=("lease_commence_year", "median"), last_sold=("month", "max")
    )
    addresses["lease_commence_year"] = addresses["lease_commence_year"].round().astype(int)
    blocks = match_blocks(addresses, buildings)
    found = blocks["location_source"] != "none"
    features = block_features(blocks[found], PlaceIndex(places, connectors, cfg), cfg)
    located = blocks.join(features)

    store.write("gold_places", places, mode="overwrite")
    store.write("gold_park_connectors", connectors, mode="overwrite")
    store.write("gold_block_locations", located, mode="overwrite")
    on_outline = blocks.loc[blocks["location_source"] == "building", "sales"].sum()
    return {
        "available": True,
        "blocks": len(blocks),
        "blocks_by_source": blocks["location_source"].value_counts().to_dict(),
        "sales_on_own_outline_pct": round(float(on_outline / blocks["sales"].sum() * 100), 2),
        "places": places["category"].value_counts().to_dict(),
        "connector_lines": len(connectors),
        "notes": notes,
    }


def _load_block_locations(store: TableStore) -> pd.DataFrame | None:
    return store.read("gold_block_locations") if store.exists("gold_block_locations") else None


def step_forecast(store: TableStore, cfg: dict[str, Any], serving_dir: Path, track: bool = True) -> dict[str, Any]:
    market_monthly = store.read("gold_market_monthly")
    market_monthly["month"] = pd.to_datetime(market_monthly["month"])
    result = run_forecast(market_monthly, cfg)

    store.write("gold_forecast_features", result.features)
    store.write("gold_forecast", result.forecast)
    store.write("gold_forecast_backtest", result.backtest)
    store.write("gold_forecast_metrics", result.metrics)

    run_id = None
    if track:
        from flatfair.tracking import configure_mlflow, log_forecast

        configure_mlflow(cfg)
        run_id = log_forecast(result, cfg)

    meta = {
        **result.info,
        "metrics": result.metrics.to_dict("records"),
        "metrics_by_horizon": result.metrics_by_horizon.to_dict("records"),
        "intervals": result.intervals.to_dict("records"),
        "mlflow_run_id": run_id,
    }
    write_json(serving_dir / "forecast_meta.json", meta)
    return meta


def step_fair_value(store: TableStore, cfg: dict[str, Any], serving_dir: Path, track: bool = True) -> dict[str, Any]:
    silver = store.read("silver_hdb_resale")
    market_index = store.read("gold_market_index")
    for frame in (silver, market_index):
        frame["month"] = pd.to_datetime(frame["month"])
    last_month = last_complete_month(silver)
    result = train_fair_value(silver, market_index, last_month, cfg, block_locations=_load_block_locations(store))

    store.write("gold_fair_value_metrics", result.metrics)
    store.write("gold_fair_value_importance", result.importance)

    run_id = None
    if track:
        from flatfair.tracking import configure_mlflow, log_fair_value

        configure_mlflow(cfg)
        run_id = log_fair_value(result, cfg, result.example)

    serving_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(result.model, serving_dir / "fair_value_model.joblib")
    # "Today" for the model is the month after the last complete one.
    now_month = last_month + pd.DateOffset(months=1)
    index_now = market_index.loc[market_index["month"] == now_month, "market_index_psm"]
    if index_now.empty:
        raise ValueError(f"Market index has no value for {now_month:%Y-%m}; rerun the gold step")
    meta = {
        **result.info,
        "metrics": result.metrics.to_dict("records"),
        "importance": result.importance.to_dict("records"),
        "intervals": result.intervals.to_dict("records"),
        "market_index_psm_now": float(index_now.iloc[0]),
        "months_since_start_now": int(months_since_start(pd.Series([now_month])).iloc[0]),
        "valuation_month": now_month.strftime("%Y-%m"),
        "mlflow_run_id": run_id,
    }
    write_json(serving_dir / "fair_value_meta.json", meta)
    return meta


def step_publish(store: TableStore, cfg: dict[str, Any], serving_dir: Path) -> dict[str, Any]:
    """Write the small, self-contained bundle the app reads at start-up."""
    serving_dir.mkdir(parents=True, exist_ok=True)
    for required in ("forecast_meta.json", "fair_value_meta.json", "fair_value_model.joblib"):
        if not (serving_dir / required).exists():
            raise FileNotFoundError(f"{required} is missing from {serving_dir}; run the forecast and fairvalue steps first")

    tables = {
        "transactions": store.read("gold_comparable_transactions")[SERVING_TRANSACTION_COLUMNS],
        "market_monthly": store.read("gold_market_monthly"),
        "town_summary": pd.concat([store.read("gold_town_summary"), store.read("gold_flat_type_summary")], ignore_index=True),
        "forecast": store.read("gold_forecast"),
    }
    income = _load_income(store)
    if income is not None:
        tables["income"] = income
    for name, frame in tables.items():
        frame.attrs = {}
        for column in ("month", "origin_month", "as_of_month"):
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column])
        frame.to_parquet(serving_dir / f"{name}.parquet", index=False)

    has_map = store.exists("gold_town_map")
    if has_map:
        town_map = town_map_from_frame(store.read("gold_town_map"))
        town_map["source"] = {k: cfg["sources"]["planning_areas"][k] for k in ("dataset_id", "name", "publisher")}
        write_json(serving_dir / "town_map.json", town_map)

    blocks = _load_block_locations(store)
    has_location = blocks is not None
    place_counts: dict[str, int] = {}
    if has_location:
        blocks = blocks[blocks["location_source"] != "none"].drop(columns=["last_sold"])
        blocks.to_parquet(serving_dir / "blocks.parquet", index=False)
        places = store.read("gold_places")
        places.to_parquet(serving_dir / "places.parquet", index=False)
        store.read("gold_park_connectors").to_parquet(serving_dir / "park_connectors.parquet", index=False)
        place_counts = places["category"].value_counts().to_dict()

    quality = json.loads(store.read("gold_data_quality").iloc[0]["summary_json"])
    meta = {
        "flatfair_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_complete_month": quality["last_complete_month"],
        "quality": quality,
        "forecast": read_json(serving_dir / "forecast_meta.json"),
        "fair_value": read_json(serving_dir / "fair_value_meta.json"),
        "affordability_assumptions": cfg["affordability"],
        "comparables": cfg["fair_value"]["comparables"],
        "policy_events": cfg["policy_events"],
        "sources": {
            "hdb_resale": {k: cfg["sources"]["hdb_resale"][k] for k in ("dataset_id", "name", "publisher")},
            "income": {k: cfg["sources"]["income"][k] for k in ("table_id", "publisher")} if income is not None else None,
            "planning_areas": {k: cfg["sources"]["planning_areas"][k] for k in ("dataset_id", "name", "publisher")} if has_map else None,
            "hdb_buildings": {k: cfg["sources"]["hdb_buildings"][k] for k in ("dataset_id", "name", "publisher")} if has_location else None,
            "places": {
                key: {k: source[k] for k in ("dataset_id", "name", "publisher") if k in source}
                for key, source in cfg["sources"]["places"].items()
            } if has_location else None,
        },
        "location": {**cfg["location"], "blocks": len(blocks), "places": place_counts} if has_location else None,
        "tables": {name: len(frame) for name, frame in tables.items()},
        "has_income_benchmark": income is not None,
        "has_town_map": has_map,
        "has_location": has_location,
    }
    write_json(serving_dir / "meta.json", meta)
    log.info("Published serving bundle to %s", serving_dir)
    return {"serving_dir": str(serving_dir), "tables": meta["tables"]}


def run(
    store: TableStore,
    cfg: dict[str, Any],
    serving_dir: Path,
    steps: list[str] | None = None,
    method: str | None = None,
    track: bool = True,
    boundaries_file: str | None = None,
    fetch_places: bool = True,
) -> dict[str, Any]:
    steps = steps or STEPS
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        raise ValueError(f"Unknown pipeline steps {unknown}; choose from {STEPS}")
    results: dict[str, Any] = {}
    # Always run in pipeline order, whatever order the steps were named in.
    for step in [s for s in STEPS if s in steps]:
        log.info("=== %s ===", step)
        if step == "ingest":
            results[step] = step_ingest(store, cfg, method=method)
        elif step == "transform":
            results[step] = step_transform(store, cfg)
        elif step == "gold":
            results[step] = step_gold(store, cfg)
        elif step == "boundaries":
            results[step] = step_boundaries(store, cfg, source_file=boundaries_file)
        elif step == "places":
            results[step] = step_places(store, cfg, fetch=fetch_places)
        elif step == "forecast":
            results[step] = step_forecast(store, cfg, serving_dir, track=track)
        elif step == "fairvalue":
            results[step] = step_fair_value(store, cfg, serving_dir, track=track)
        elif step == "publish":
            results[step] = step_publish(store, cfg, serving_dir)
    return results
