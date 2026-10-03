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
    "silver_hdb_resale": "Typed and standardised transactions. Nothing is dropped: invalid rows, exact duplicates and unusual prices are flagged with reasons.",
    "gold_data_quality": "Latest data quality summary: row counts, check results and the full summary as JSON.",
    "gold_market_monthly": "Monthly median, mean, quartiles, volume and price per sqm by town x flat type, with ALL rollups, MoM/YoY and rolling averages.",
    "gold_town_summary": "Current market per town x flat type: 12-month and 3-month medians, YoY, momentum and five-year change.",
    "gold_flat_type_summary": "National market per flat type, same measures as gold_town_summary.",
    "gold_market_index": "National median price per sqm over the preceding three months; used to bring fair value estimates to today's price level.",
    "gold_comparable_transactions": "Valid transactions with the fields used for comparable-sale search.",
    "gold_affordability": "Repayment and price-to-income for each town x flat type at the official median household income.",
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
    source = "SingStat M810361" if name == "bronze_income" else SOURCE
    try:
        spark.sql(f"ALTER TABLE {fqn} SET TAGS ('project' = 'flatfair', 'layer' = '{layer}', 'source' = '{source}')")
    except Exception as exc:  # noqa: BLE001 - tags are optional metadata
        log.warning("Could not tag %s (%s); comments were still applied", fqn, exc)
