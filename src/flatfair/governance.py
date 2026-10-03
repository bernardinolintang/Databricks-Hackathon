"""Unity Catalog documentation for every FlatFair table.

Applied after each Delta write so the catalog explains itself: what a table
holds, which layer it belongs to, and where its data came from.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

SOURCE = "data.gov.sg d_8b84c4ee58e3cfc0ece0d773c8ca6abc (HDB)"

TABLES: dict[str, str] = {
    "bronze_hdb_resale": "Raw HDB resale transactions exactly as published on data.gov.sg; full snapshot replaced each run. All columns are text.",
    "bronze_ingestion_log": "One row per ingestion run: method, row counts, schema check, source timestamp and content hash.",
    "bronze_income": "SingStat M810361: median monthly household employment income (incl. employer CPF) of resident employed households, by year.",
    "bronze_planning_areas": "URA Master Plan 2019 planning area boundaries from data.gov.sg; geometry kept verbatim as GeoJSON coordinates.",
    "bronze_hdb_buildings": "HDB Existing Building outlines from data.gov.sg, one row per block: block number, HDB street code, postal code and the centre of the outline.",
    "bronze_places": "Places near flats as published: MRT and LRT exits and bus stops (LTA), schools (MOE, placed with OneMap), hawker centres (NEA), parks (NParks) and malls (OpenStreetMap).",
    "bronze_park_connectors": "NParks Park Connector Loop lines from data.gov.sg; geometry kept as GeoJSON coordinates.",
    "silver_hdb_resale": "Typed and standardised transactions. Nothing is dropped: invalid rows, exact duplicates and unusual prices are flagged with reasons.",
    "gold_data_quality": "Latest data quality summary: row counts, check results and the full summary as JSON.",
    "gold_market_monthly": "Monthly median, mean, quartiles, volume and price per sqm by town x flat type, with ALL rollups, MoM/YoY and rolling averages.",
    "gold_town_summary": "Current market per town x flat type: 12-month and 3-month medians, YoY, momentum and five-year change.",
    "gold_flat_type_summary": "National market per flat type, same measures as gold_town_summary.",
    "gold_market_index": "National median price per sqm over the preceding three months; used to bring fair value estimates to today's price level.",
    "gold_comparable_transactions": "Valid transactions with the fields used for comparable-sale search.",
    "gold_affordability": "Repayment and price-to-income for each town x flat type at the official median household income.",
    "gold_town_map": "Simplified SVG shapes for the 26 HDB towns (drawn from planning areas) plus surrounding land, for the app's town map.",
    "gold_block_locations": "One row per block with a resale record: its position (matched to HDB's building outline) and its distance to the nearest MRT, any station, bus stop, primary school, mall, hawker centre, park and park connector, plus counts of bus stops within 400 m and primary schools within 1 km.",
    "gold_places": "Cleaned places the app lists and maps: category, kind, name and position. Malls mapped twice in OpenStreetMap are kept once.",
    "gold_park_connectors": "Park connector lines simplified for the map, as [latitude, longitude] paths.",
    "gold_forecast_features": "Lag, momentum and volume features per series, origin month and horizon used to train the forecast model.",
    "gold_forecast": "Published six-month forecast with 80% empirical range per town x flat type.",
    "gold_forecast_backtest": "Rolling-origin backtest predictions from every forecast method, with actuals.",
    "gold_forecast_metrics": "Backtest MAE, RMSE and MAPE by forecast method; the selected method is flagged.",
    "gold_fair_value_metrics": "Holdout accuracy of the fair value models and the rule-of-thumb baseline.",
    "gold_fair_value_importance": "Permutation importance of each fair value input on the holdout set.",
}


def apply(spark: Any, fqn: str, name: str) -> None:
    """Comment and tag one table. Tag support varies by workspace, so a
    failure is logged and the pipeline continues."""
    comment = TABLES.get(name)
    if comment:
        spark.sql(f"COMMENT ON TABLE {fqn} IS '{comment.replace(chr(39), chr(39) * 2)}'")
    layer = name.split("_", 1)[0]
    other_sources = {
        "bronze_income": "SingStat M810361",
        "bronze_planning_areas": "data.gov.sg d_4765db0e87b9c86336792efe8a1f7a66 (URA)",
        "gold_town_map": "data.gov.sg d_4765db0e87b9c86336792efe8a1f7a66 (URA)",
        "bronze_hdb_buildings": "data.gov.sg d_16b157c52ed637edd6ba1232e026258d (HDB)",
        "bronze_places": "data.gov.sg (LTA, MOE, NEA, NParks); OneMap (SLA); OpenStreetMap",
        "bronze_park_connectors": "data.gov.sg d_a69ef89737379f231d2ae93fd1c5707f (NParks)",
        "gold_places": "data.gov.sg (LTA, MOE, NEA, NParks); OneMap (SLA); OpenStreetMap",
        "gold_park_connectors": "data.gov.sg d_a69ef89737379f231d2ae93fd1c5707f (NParks)",
        "gold_block_locations": "data.gov.sg (HDB resale and building outlines, LTA, MOE, NEA, NParks); OpenStreetMap",
    }
    source = other_sources.get(name, SOURCE)
    try:
        spark.sql(f"ALTER TABLE {fqn} SET TAGS ('project' = 'flatfair', 'layer' = '{layer}', 'source' = '{source}')")
    except Exception as exc:  # noqa: BLE001 - tags are optional metadata
        log.warning("Could not tag %s (%s); comments were still applied", fqn, exc)
